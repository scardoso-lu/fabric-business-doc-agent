"""
Fabric Business Documentation Agent — CLI

Usage examples:

  # Document all pipelines and notebooks found under ./src
  python -m agent.main --src ./src

  # Document a specific directory
  python -m agent.main --src ./src/mslearn-fabric --output ./docs

  # Document only notebooks (skip pipeline JSONs)
  python -m agent.main --src ./src --notebooks-only

  # Document only pipeline JSONs
  python -m agent.main --src ./src --pipelines-only
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

import agent.prompts as prompts
from agent.ai.client_factory import create_client
from agent.config import ARTIFACT_TYPES, CONTEXT_FILE, CONTEXT_TEXT, GITHUB_REPO_URL, OUTPUT_DIR, PROMPTS_FILE, PUBLISH_WIKI, SRC_DIR
from agent.git_cloner import clone_repo
from agent.rag.indexer import DocGroup, build_keyword_index, build_vector_index
from agent.rag.retriever import RAGRetriever
from agent.generators.doc_generator import (
    generate_dataflow_doc,
    generate_notebook_doc,
    generate_pipeline_doc,
    generate_powerautomate_doc,
    get_linked_dataflows,
    get_linked_notebooks,
)
from agent.parsers.dataflow_parser import ParsedDataflow, find_dataflow_files, parse_dataflow_file
from agent.parsers.notebook_parser import ParsedNotebook, find_notebook_files, parse_notebook_file
from agent.parsers.pipeline_parser import find_pipeline_files, parse_pipeline_file
from agent.parsers.parser_registry import get_parser
from agent.parsers.powerautomate_parser import ParsedPowerAutomateFlow
from agent.publishers.base_wiki_publisher import BaseWikiPublisher
from agent.publishers.wiki_factory import create_wiki_publisher

console = Console()


@click.command()
@click.option(
    "--src",
    "src_dir",
    default=None,
    show_default=True,
    help="Root directory to scan for pipeline JSON and notebook files.",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option(
    "--output",
    "output_dir",
    default=str(OUTPUT_DIR),
    show_default=True,
    help="Directory where generated .md files are written.",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--pipelines-only", is_flag=True, default=False, help="Only process pipeline JSON files.")
@click.option("--notebooks-only", is_flag=True, default=False, help="Only process notebook .ipynb files.")
@click.option("--dataflows-only", is_flag=True, default=False, help="Only process Dataflow Gen2 files.")
@click.option("--powerautomate-only", is_flag=True, default=False, help="Only process Power Automate flow files.")
@click.option(
    "--pipeline",
    "pipeline_filter",
    default=None,
    help="Process only the pipeline whose file stem matches this value.",
)
@click.option(
    "--notebook",
    "notebook_filter",
    default=None,
    help="Process only the notebook whose file stem matches this value.",
)
@click.option(
    "--dataflow",
    "dataflow_filter",
    default=None,
    help="Process only the dataflow whose name matches this value.",
)
@click.option(
    "--powerautomate",
    "powerautomate_filter",
    default=None,
    help="Process only the Power Automate flow whose file stem matches this value.",
)
def main(
    src_dir: Path,
    output_dir: Path,
    pipelines_only: bool,
    notebooks_only: bool,
    dataflows_only: bool,
    powerautomate_only: bool,
    pipeline_filter: str | None,
    notebook_filter: str | None,
    dataflow_filter: str | None,
    powerautomate_filter: str | None,
) -> None:
    console.print(Panel.fit("[bold cyan]Fabric Business Documentation Agent[/bold cyan]"))

    output_dir.mkdir(parents=True, exist_ok=True)
    for f in output_dir.glob("*.md"):
        f.unlink()

    # ------------------------------------------------------------------
    # Prompts file (optional — per-section prompt customisation)
    # ------------------------------------------------------------------
    prompts_path = Path(PROMPTS_FILE) if PROMPTS_FILE else None
    prompts.initialise(prompts_path)
    if prompts_path and prompts_path.exists():
        console.print(f"[dim]Prompts loaded from [italic]{prompts_path}[/italic][/dim]\n")

    # ------------------------------------------------------------------
    # Context file (optional — enriches system prompt with org/project info)
    # ------------------------------------------------------------------
    if CONTEXT_FILE and not CONTEXT_TEXT:
        console.print(f"[bold yellow]Warning:[/bold yellow] CONTEXT_FILE is set to '{CONTEXT_FILE}' but the file could not be read. Context will not be applied.\n")
    elif CONTEXT_TEXT:
        console.print(f"[dim]Context loaded from [italic]{CONTEXT_FILE}[/italic] ({len(CONTEXT_TEXT)} chars)[/dim]\n")

    # ------------------------------------------------------------------
    # Clone repository (if GITHUB_REPO_URL is set)
    # ------------------------------------------------------------------
    clone_dir = SRC_DIR
    if GITHUB_REPO_URL:
        console.print(f"Cloning [bold]{GITHUB_REPO_URL}[/bold] …")
        try:
            clone_repo(GITHUB_REPO_URL, clone_dir)
            console.print(f"  [green]✓[/green] Cloned to [italic]{clone_dir}[/italic]\n")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[bold red]Error:[/bold red] Failed to clone repository: {exc}")
            sys.exit(1)
        if src_dir is None:
            src_dir = clone_dir
    elif src_dir is None:
        src_dir = SRC_DIR

    if not src_dir.exists():
        console.print(f"[bold red]Error:[/bold red] Source directory not found: {src_dir}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Discover source files
    # Enabled types come from ARTIFACT_TYPES in .env; CLI *-only flags
    # further restrict the set for a single run.
    # ------------------------------------------------------------------
    enabled_types = set(ARTIFACT_TYPES)
    any_only = pipelines_only or notebooks_only or dataflows_only or powerautomate_only
    if any_only:
        requested: set[str] = set()
        if pipelines_only:      requested.add("pipeline")
        if notebooks_only:      requested.add("notebook")
        if dataflows_only:      requested.add("dataflow")
        if powerautomate_only:  requested.add("powerautomate")
        scan_types = enabled_types & requested
    else:
        scan_types = enabled_types

    scan_pipelines      = "pipeline"      in scan_types
    scan_notebooks      = "notebook"      in scan_types
    scan_dataflows      = "dataflow"      in scan_types
    scan_powerautomate  = "powerautomate" in scan_types

    notebook_files = find_notebook_files(src_dir) if scan_notebooks else []
    pipeline_files = find_pipeline_files(src_dir) if scan_pipelines else []
    dataflow_files = find_dataflow_files(src_dir) if scan_dataflows else []

    if notebook_filter:
        notebook_files = [f for f in notebook_files if f.stem == notebook_filter]
    if pipeline_filter:
        pipeline_files = [f for f in pipeline_files if f.stem == pipeline_filter]
    if dataflow_filter:
        dataflow_files = [f for f in dataflow_files if f.stem == dataflow_filter]

    # Power Automate — discovered via parser registry
    powerautomate_map: dict[str, ParsedPowerAutomateFlow] = {}
    if scan_powerautomate:
        pa_parser = get_parser("powerautomate")
        if pa_parser:
            for pa_path in pa_parser.find_files(src_dir, name_filter=powerautomate_filter):
                flow = pa_parser.parse(pa_path)
                if flow:
                    powerautomate_map[flow.name] = flow

    pa_count = len(powerautomate_map)
    console.print(
        f"Found [bold]{len(pipeline_files)}[/bold] pipeline(s), "
        f"[bold]{len(notebook_files)}[/bold] notebook(s), "
        f"[bold]{len(dataflow_files)}[/bold] dataflow(s), and "
        f"[bold]{pa_count}[/bold] Power Automate flow(s) under [italic]{src_dir}[/italic]"
    )

    if not pipeline_files and not notebook_files and not dataflow_files and not powerautomate_map:
        console.print("[yellow]Nothing to process. Exiting.[/yellow]")
        sys.exit(0)

    # ------------------------------------------------------------------
    # Parse all notebooks and dataflows upfront (needed for pipeline linking)
    # ------------------------------------------------------------------
    notebook_map: dict[str, ParsedNotebook] = {}
    for nb_path in notebook_files:
        nb = parse_notebook_file(nb_path)
        if nb:
            notebook_map[nb.name] = nb

    dataflow_map: dict[str, ParsedDataflow] = {}
    for df_path in dataflow_files:
        df = parse_dataflow_file(df_path)
        if df:
            dataflow_map[df.name] = df

    # ------------------------------------------------------------------
    # Parse all pipelines upfront and identify linked notebooks/dataflows.
    # Linked items are documented within their pipeline's doc
    # and do NOT get a standalone .md file.
    # ------------------------------------------------------------------
    parsed_pipelines = []
    linked_notebooks: dict[str, str] = {}
    linked_dataflows: dict[str, str] = {}

    for pf in pipeline_files:
        pipeline = parse_pipeline_file(pf)
        if not pipeline:
            continue
        parsed_pipelines.append(pipeline)
        for nb_name in get_linked_notebooks(pipeline, notebook_map):
            linked_notebooks[nb_name] = pipeline.name
        for df_name in get_linked_dataflows(pipeline, dataflow_map):
            linked_dataflows[df_name] = pipeline.name

    orphan_notebooks = {
        name: nb for name, nb in notebook_map.items()
        if name not in linked_notebooks
    }
    orphan_dataflows = {
        name: df for name, df in dataflow_map.items()
        if name not in linked_dataflows
    }

    console.print(
        f"  {len(parsed_pipelines)} pipeline(s) · "
        f"{len(linked_notebooks)} linked notebook(s) · "
        f"{len(orphan_notebooks)} orphan notebook(s) · "
        f"{len(linked_dataflows)} linked dataflow(s) · "
        f"{len(orphan_dataflows)} orphan dataflow(s) · "
        f"{pa_count} Power Automate flow(s)\n"
    )

    # ------------------------------------------------------------------
    # Initialise LLM client
    # ------------------------------------------------------------------
    try:
        client = create_client()
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)

    console.print(f"Using [bold]{client.provider}[/bold] / [bold]{client.model}[/bold]\n")

    # ------------------------------------------------------------------
    # Build RAG index (skipped for providers that don't use retrieval)
    # ------------------------------------------------------------------
    if client.supports_rag:
        doc_groups: list[DocGroup] = []
        for pipeline in parsed_pipelines:
            linked_nbs = [
                notebook_map[name]
                for name in get_linked_notebooks(pipeline, notebook_map)
                if name in notebook_map
            ]
            linked_dfs = [
                dataflow_map[name]
                for name in get_linked_dataflows(pipeline, dataflow_map)
                if name in dataflow_map
            ]
            doc_groups.append(DocGroup(group_id=pipeline.name, pipeline=pipeline, notebooks=linked_nbs, dataflows=linked_dfs))
        for nb_name, nb in orphan_notebooks.items():
            doc_groups.append(DocGroup(group_id=nb_name, pipeline=None, notebooks=[nb]))
        for df_name, df in orphan_dataflows.items():
            doc_groups.append(DocGroup(group_id=df_name, pipeline=None, dataflows=[df]))
        for flow_name, flow in powerautomate_map.items():
            doc_groups.append(DocGroup(group_id=flow_name, flows=[flow]))

        console.print("[bold]Building RAG index…[/bold]")

        keyword_index = build_keyword_index(doc_groups)

        qdrant_client = None
        if client.embedding_model:
            try:
                qdrant_client = build_vector_index(doc_groups, client)
            except Exception as exc:  # noqa: BLE001
                console.print(f"  [yellow]Vector index failed ({exc}) — using keyword index.[/yellow]")

        retriever = RAGRetriever(keyword_index, qdrant=qdrant_client, llm_client=client)
        mode = "vector + keyword fallback" if qdrant_client else "keyword"
        console.print(f"  [green]✓[/green] Indexed [bold]{len(doc_groups)}[/bold] group(s) — [{mode}]\n")

        client.set_retriever(retriever)
    else:
        console.print("[dim]RAG skipped — local Claude agent handles full context directly.[/dim]\n")

    # ------------------------------------------------------------------
    # Initialise wiki publisher (optional)
    # ------------------------------------------------------------------
    wiki: BaseWikiPublisher | None = None
    if PUBLISH_WIKI:
        try:
            wiki = create_wiki_publisher()
            console.print("[bold]Wiki publishing enabled.[/bold]\n")
        except ValueError as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")
            sys.exit(1)

    errors: list[str] = []

    # ------------------------------------------------------------------
    # Process pipelines (linked notebooks are embedded as tasks)
    # ------------------------------------------------------------------
    if parsed_pipelines:
        console.print("[bold]Generating pipeline documentation…[/bold]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Processing…", total=len(parsed_pipelines))
            for pipeline in parsed_pipelines:
                progress.update(task, description=f"Pipeline: [cyan]{pipeline.name}[/cyan]")
                try:
                    if wiki and wiki.page_exists(pipeline.name):
                        console.print(f"  [dim]⏭  {pipeline.name} — wiki page exists, skipping.[/dim]")
                        continue
                    markdown = generate_pipeline_doc(pipeline, notebook_map, client, dataflow_map)
                    out_path = output_dir / f"{pipeline.name}.md"
                    out_path.write_text(markdown, encoding="utf-8")
                    msg = f"  [green]✓[/green] {out_path.name}"
                    if wiki:
                        url = wiki.publish(pipeline.name, markdown)
                        msg += f" → [dim]{url}[/dim]"
                    console.print(msg)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Error generating docs for pipeline {pipeline.name}: {exc}")
                finally:
                    progress.advance(task)

    # ------------------------------------------------------------------
    # Process orphan notebooks (not linked to any pipeline)
    # ------------------------------------------------------------------
    if orphan_notebooks:
        console.print("\n[bold]Generating orphan notebook documentation…[/bold]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Processing…", total=len(orphan_notebooks))
            for nb_name, notebook in orphan_notebooks.items():
                progress.update(task, description=f"Notebook: [cyan]{nb_name}[/cyan]")
                try:
                    if wiki and wiki.page_exists(nb_name):
                        console.print(f"  [dim]⏭  {nb_name} — wiki page exists, skipping.[/dim]")
                        continue
                    markdown = generate_notebook_doc(notebook, client)
                    out_path = output_dir / f"{nb_name}.md"
                    out_path.write_text(markdown, encoding="utf-8")
                    msg = f"  [green]✓[/green] {out_path.name}"
                    if wiki:
                        url = wiki.publish(nb_name, markdown)
                        msg += f" → [dim]{url}[/dim]"
                    console.print(msg)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Error generating docs for notebook {nb_name}: {exc}")
                finally:
                    progress.advance(task)

    if linked_notebooks and not orphan_notebooks:
        console.print(
            "\n[dim]All notebooks are linked to pipelines — "
            "no standalone notebook docs generated.[/dim]"
        )

    # ------------------------------------------------------------------
    # Process orphan dataflows (not linked to any pipeline)
    # ------------------------------------------------------------------
    if orphan_dataflows:
        console.print("\n[bold]Generating orphan dataflow documentation…[/bold]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Processing…", total=len(orphan_dataflows))
            for df_name, dataflow in orphan_dataflows.items():
                progress.update(task, description=f"Dataflow: [cyan]{df_name}[/cyan]")
                try:
                    if wiki and wiki.page_exists(df_name):
                        console.print(f"  [dim]⏭  {df_name} — wiki page exists, skipping.[/dim]")
                        continue
                    markdown = generate_dataflow_doc(dataflow, client)
                    out_path = output_dir / f"{df_name}.md"
                    out_path.write_text(markdown, encoding="utf-8")
                    msg = f"  [green]✓[/green] {out_path.name}"
                    if wiki:
                        url = wiki.publish(df_name, markdown)
                        msg += f" → [dim]{url}[/dim]"
                    console.print(msg)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Error generating docs for dataflow {df_name}: {exc}")
                finally:
                    progress.advance(task)

    if linked_dataflows and not orphan_dataflows:
        console.print(
            "\n[dim]All dataflows are linked to pipelines — "
            "no standalone dataflow docs generated.[/dim]"
        )

    # ------------------------------------------------------------------
    # Process Power Automate flows
    # ------------------------------------------------------------------
    if powerautomate_map:
        console.print("\n[bold]Generating Power Automate flow documentation…[/bold]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Processing…", total=len(powerautomate_map))
            for flow_name, flow in powerautomate_map.items():
                progress.update(task, description=f"Flow: [cyan]{flow_name}[/cyan]")
                try:
                    if wiki and wiki.page_exists(flow_name):
                        console.print(f"  [dim]⏭  {flow_name} — wiki page exists, skipping.[/dim]")
                        continue
                    markdown = generate_powerautomate_doc(flow, client)
                    out_path = output_dir / f"{flow_name}.md"
                    out_path.write_text(markdown, encoding="utf-8")
                    msg = f"  [green]✓[/green] {out_path.name}"
                    if wiki:
                        url = wiki.publish(flow_name, markdown)
                        msg += f" → [dim]{url}[/dim]"
                    console.print(msg)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Error generating docs for Power Automate flow {flow_name}: {exc}")
                finally:
                    progress.advance(task)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    console.print()
    if errors:
        console.print(f"[bold yellow]Completed with {len(errors)} error(s):[/bold yellow]")
        for e in errors:
            console.print(f"  [red]✗[/red] {e}")
    else:
        console.print("[bold green]All documentation generated successfully.[/bold green]")

    console.print(f"\nOutput written to: [italic]{output_dir}[/italic]")


if __name__ == "__main__":
    main()
