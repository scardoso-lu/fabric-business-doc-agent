# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Agent

```bash
# Sync dependencies (first time or after pyproject.toml changes)
uv sync

# Run against a source directory
uv run agent --src ./src --output ./output

# Filter by type or name
uv run agent --src ./src --pipelines-only
uv run agent --src ./src --notebooks-only
uv run agent --src ./src --dataflows-only
uv run agent --src ./src --powerautomate-only
uv run agent --src ./src --pipeline "pipeline_name"
uv run agent --src ./src --notebook "notebook_name"
uv run agent --src ./src --dataflow "dataflow_name"
uv run agent --src ./src --powerautomate "flow_name"

# Windows/Linux convenience wrappers (sync deps, run agent, open output)
run.bat [src_dir] [output_dir]
run.sh  [src_dir] [output_dir]
```

Run the test suite: `uv run pytest`

## Prompt Customisation

Each section prompt lives in its own file inside the `prompts/` folder. Edit the file for the section you want to change; the next run picks it up. Missing files fall back to built-in defaults.

```
prompts/
  system_prompt.md          lineage_system_prompt.md
  purpose.md                flow.md
  business_goal.md          data_quality.md
  column_lineage.md
```

File format: the entire file content is the prompt body. Lines starting with `>` are editorial notes stripped before the LLM call. Sub-prompts within a file are separated by a line containing only `---`.

Template variables: `{{name}}` (artifact name), `{{content}}` (extracted source data), `{{rag_context}}` (RAG background, empty when RAG is disabled).

Override the folder via `PROMPTS_DIR=./my_prompts` in `.env`.

`agent/prompts.py` owns loading (`initialise` — accepts a directory or legacy single file), retrieval (`get`), and rendering (`render`). `_parse_dir()` loads from a folder; `_parse_file()` loads from the legacy single-file format. Both `LLMClient` and `LocalClaudeClient` call `prompts.render(prompts.get(key), ...)` in every section method.

## End-to-End Data Flow

```
GITHUB_REPO_URL set?
  └─ Yes → git_cloner.clone_repo() → wipes ./src, clones fresh, checks out main/master

main.py
  ├─ Clears output/*.md
  ├─ Reads ARTIFACT_TYPES from config (default: pipeline,notebook,dataflow)
  ├─ CLI *-only flags further restrict which types are scanned for this run
  ├─ Discovers files for each enabled type (parsers injected via parser_registry)
  ├─ Parses all notebooks (notebook_map) and dataflows (dataflow_map)
  ├─ Parses all pipelines → resolves linked notebooks/dataflows → identifies orphans
  ├─ Discovers and parses Power Automate flows (via _PowerAutomateParser)
  ├─ create_client() → returns LocalClaudeClient or LLMClient based on LLM_PROVIDER
  ├─ Builds RAG index (skipped when client.supports_rag is False)
  │     ├─ build_keyword_index() — always, all providers
  │     └─ build_vector_index() — only OpenAI/Ollama (embeddings API)
  │         → RAGRetriever: vector search with keyword fallback
  ├─ For each pipeline → generate_pipeline_doc() → writes {name}.md
  ├─ For each orphan notebook → generate_notebook_doc() → writes {name}.md
  ├─ For each orphan dataflow → generate_dataflow_doc() → writes {name}.md
  ├─ For each Power Automate flow → generate_powerautomate_doc() → writes {name}.md
  └─ PUBLISH_WIKI=true → WikiPublisher.publish() pushes each .md to wiki
```

## Document Structure

Every output file — pipeline or notebook — produces the **same five sections**:

| Section | Content |
|---|---|
| **Purpose** | Why this process exists; what business need it serves |
| **Flow** | Data flow as prose (max 2 paragraphs) + a Mermaid `flowchart LR` diagram |
| **Business Goal** | Outcome delivered; what breaks if it doesn't run |
| **Data Quality & Alerts** | Validation checks and rules (may use bullet lists) |
| **Column Lineage** | Column-by-column mapping from bronze source to gold output |

Each section is a separate LLM call with tailored content. `doc_generator._pipeline_contents()` and `_notebook_contents()` build context strings (one per section) so each call receives only the most relevant information.

**Formatting rules enforced via system prompt:**
- Short paragraphs; plain English; active voice; present tense
- Be specific — avoid vague phrases like "the process" when a clearer description exists
- Bullet points only for rules, conditions, or checks
- No headings or code blocks unless explicitly requested (the Flow diagram is an explicit request)
- Technical terms avoided; when necessary, used once and briefly explained

## LLM Client Architecture

Clients are selected via dependency injection using `create_client()` in `agent/ai/client_factory.py`. All clients implement `BaseLLMClient` (`agent/ai/base_client.py`).

| Provider (`LLM_PROVIDER`) | Class | RAG | Notes |
|---|---|---|---|
| `anthropic` | `LLMClient` | keyword index | Prompt caching applied; no embeddings API |
| `openai` | `LLMClient` | vector + keyword | Embeddings via `text-embedding-3-small` |
| `ollama` | `LLMClient` | vector + keyword | Embeddings via `nomic-embed-text`; no API key |
| `local` | `LocalClaudeClient` | none | Calls `claude -p` subprocess; no API key or embeddings needed |

`LocalClaudeClient` sets `supports_rag = False`, which causes `main.py` to skip building the RAG index entirely.

### Flow section and Mermaid diagrams

`section_flow()` uses `_call_flow()` instead of `_call()`. The difference: `_call_flow()` passes the output through `_clean_flow_output()`, which splits the response at the `\`\`\`mermaid` fence, cleans only the prose portion with `_clean_output()`, and reassembles with the diagram block intact.

## RAG Architecture

Two index tiers are built when `client.supports_rag` is True:

1. **Keyword index** (`build_keyword_index`) — always present for RAG-enabled providers. Dict of `group_id → [text chunks]`. Retrieval by word-overlap scoring.
2. **Vector index** (`build_vector_index`) — OpenAI/Ollama only. In-memory Qdrant with cosine similarity. Falls back to keyword search if unavailable.

Each `DocGroup` scopes one pipeline + its linked notebooks, or one orphan notebook. RAG queries are filtered to the same `group_id` so context never crosses document boundaries.

Chunks are sanitized on ingestion to strip instruction-like lines (lines starting with "return", "write", "do not", `%%`, etc.) which could corrupt LLM prompts.

## Azure DevOps Wiki Publishing

Set `PUBLISH_WIKI=true` in `.env` to push every generated `.md` file to an Azure DevOps project wiki after generation. Each file becomes one wiki page (created or updated). Pages are versioned via ETag — the publisher GETs the page first to retrieve its ETag, then PUTs with `If-Match` for safe updates.

Publisher logic lives in `agent/publishers/wiki_publisher.py`. `publisher_from_env()` validates required variables and returns a configured `WikiPublisher`.

## Configuration Reference

All settings via `.env` (copy from `.env.example`):

| Variable | Default | Notes |
|---|---|---|
| `ARTIFACT_TYPES` | `pipeline,notebook,dataflow` | Comma-separated artifact types to scan; add `powerautomate` to include Power Automate flows |
| `PROMPTS_DIR` | `./prompts` | Folder of per-section prompt files (`{key}.md`) |
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `openai`, `ollama`, or `local` |
| `LLM_MODEL` | provider default | `claude-sonnet-4-6` / `gpt-4o-mini` / `llama3.2` / ignored for `local` |
| `ANTHROPIC_API_KEY` | — | Required for `anthropic` |
| `OPENAI_API_KEY` | — | Required for `openai` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Only for `ollama` |
| `EMBEDDING_MODEL` | provider default | `text-embedding-3-small` (OpenAI) / `nomic-embed-text` (Ollama) |
| `GITHUB_REPO_URL` | — | Repo to clone into `./src` before scanning |
| `OUTPUT_DIR` | `./output` | Override default output path |
| `CONTEXT_FILE` | — | Path to a plain-text file with company/project context; appended to the system prompt |
| `PUBLISH_WIKI` | `false` | Set to `true`, `1`, or `yes` to enable wiki publishing |
| `AZDO_ORG` | — | Azure DevOps organisation name (required when `PUBLISH_WIKI=true`) |
| `AZDO_PROJECT` | — | Azure DevOps project name (required when `PUBLISH_WIKI=true`) |
| `AZDO_WIKI_ID` | — | Wiki identifier as shown in the URL (required when `PUBLISH_WIKI=true`) |
| `AZDO_PAT` | — | Personal Access Token with Wiki read/write scope (required when `PUBLISH_WIKI=true`) |
| `AZDO_WIKI_PATH_PREFIX` | — | Optional path prefix, e.g. `/Fabric Docs` |

## Parser Dependency Injection

Artifact parsers are registered in `agent/parsers/parser_registry.py`. Each parser wraps the existing `find_*` and `parse_*` functions behind the `ArtifactParser` interface (`base_parser.py`). To add a new artifact type:

1. Create a parser class in `agent/parsers/<type>_parser.py`.
2. Add a subclass of `ArtifactParser` to `parser_registry.py` and register it in `_REGISTRY`.
3. Add a generator function in `agent/generators/doc_generator.py`.
4. Add a generation loop in `agent/main.py` following the Power Automate pattern.
5. Document the new type name in `ARTIFACT_TYPES` in `.env.example`.

The `ARTIFACT_TYPES` env var (comma-separated) controls which types are scanned. CLI `--<type>-only` flags further restrict the set for a single run.

## Key Design Decisions

- **Dependency injection for LLM clients**: `create_client()` is the single entry point. `main.py` only depends on `BaseLLMClient`; no provider-specific code leaks outside the `agent/ai/` module.
- **Dependency injection for parsers**: `get_parser()` / `get_enabled_parsers()` in `parser_registry.py` is the single entry point for artifact discovery. `main.py` uses `get_parser("powerautomate")` for Power Automate; existing Fabric types keep their direct function calls for backward compatibility.
- **Notebook linking**: Notebooks referenced by a pipeline (`TridentNotebook`/`Notebook` activity type) are consumed by that pipeline's doc and do **not** get a standalone file. Orphan notebooks (unreferenced) get their own file.
- **Output cleanup**: `_clean_output()` in `llm_client.py` strips common LLM artefacts (echoed instructions, code fences, meta-comments). `_clean_flow_output()` is the variant that preserves the mermaid block.
- **Section-specific content**: Each of the 5 LLM calls receives a different slice of the parsed data — e.g. quality checks get control-flow and fail activities; the Flow section gets external source configs and linked notebook names.
- **Prompt caching**: Anthropic provider caches the system prompt across all calls in a run to reduce cost.
- **Context file**: `CONTEXT_FILE` points to a plain-text file describing the organisation, domain, or project. `build_system_prompt()` in `llm_client.py` appends it to `SYSTEM_PROMPT` at client init time. Both `LLMClient` and `LocalClaudeClient` store the result as `self._system_prompt` and use it for every call. If the file is set but unreadable, `main.py` warns and continues without context.
