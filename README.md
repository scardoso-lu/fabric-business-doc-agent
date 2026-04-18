# Fabric Business Documentation Agent

Automatically turns Microsoft Fabric artifacts — pipelines, notebooks, and Dataflow Gen2 files — into plain-English business documentation. Each artifact becomes a structured Markdown page that non-technical readers (managers, project owners, operations staff) can understand. Pages can be published directly to an Azure DevOps or Confluence wiki.

---

## How it works

The agent scans a source directory, parses every supported artifact, and calls an LLM once per document section. Each section receives only the information most relevant to it, keeping prompts focused and output concise.

For artifacts linked together — a pipeline that calls a notebook or a Dataflow Gen2 — the agent documents them as a single unit. Standalone (orphan) artifacts each get their own page.

Before writing the **Purpose** section the agent looks for related Jira issues or Azure DevOps work items. When it finds them, it uses the real business intent recorded in those tickets to ground the explanation. When nothing is found it falls back to inferring the purpose from the artifact's own data flow.

---

## What it produces

Every page has the same five sections:

| Section | What it contains |
| --- | --- |
| **Purpose** | Why this process exists — grounded in linked tickets/PRs when available, otherwise inferred from the data flow |
| **Flow** | Plain-English description of data movement (up to two paragraphs) plus a Mermaid `flowchart LR` diagram |
| **Business Goal** | The outcome delivered and what breaks downstream if it stops running |
| **Data Quality & Alerts** | Validation checks, error conditions, and failure paths |
| **Column Lineage** | Table-by-table column mapping from bronze source to gold output (where transforms are detectable) |

Output is written as `.md` files — one per pipeline, notebook, or orphan dataflow — ready to paste into any wiki or version-controlled docs folder.

---

## Supported artifact types

| Type | Source format | Notes |
| --- | --- | --- |
| **Pipeline** | Fabric pipeline JSON | Activities, dependencies, linked notebooks and dataflows |
| **Notebook** | `.ipynb` Jupyter notebook | Code cells parsed; sections extracted as headings |
| **Dataflow Gen2** | `.json` / `.dataflow` (Power Query M-code) | Three JSON layouts supported; M-code translated to plain English |
| **Power Automate Flow** | `.zip` portal export or `.json` flow definition | Triggers, actions, and connected services documented |

Pipelines that reference notebooks or dataflows document them inline. Orphan notebooks and dataflows (not referenced by any pipeline) get their own standalone pages. Power Automate flows always get their own standalone pages.

Artifact types are configured via `ARTIFACT_TYPES` in `.env` (see [Configuration reference](#configuration-reference)).

---

## Quick start

### 1. Install dependencies

```bash
# Recommended — UV manages a virtual environment automatically
uv sync

# Alternative — plain pip
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Open `.env` and set at minimum `LLM_PROVIDER` and the matching API key (or leave `LLM_PROVIDER=local` to use the Claude CLI with no API key).

### 3. Run

```bash
# Document everything under ./src
uv run agent --src ./src

# Or with plain Python
python -m agent.main --src ./src
```

```bash
# Filter by artifact type
uv run agent --src ./src --pipelines-only
uv run agent --src ./src --notebooks-only
uv run agent --src ./src --dataflows-only
uv run agent --src ./src --powerautomate-only

# Filter by name
uv run agent --src ./src --pipeline "MyPipeline"
uv run agent --src ./src --notebook "MyNotebook"
uv run agent --src ./src --dataflow "MyDataflow"
uv run agent --src ./src --powerautomate "MyFlow"

# Custom output directory
uv run agent --src ./src --output ./docs
```

Windows / Linux convenience wrappers (sync deps, run agent, open output):

```bat
run.bat [src_dir] [output_dir]
```
```bash
./run.sh [src_dir] [output_dir]
```

---

## LLM providers

Set `LLM_PROVIDER` in `.env` to choose how the agent calls the LLM.

| `LLM_PROVIDER` | What you need | RAG | Notes |
| --- | --- | --- | --- |
| `local` | [Claude CLI](https://claude.ai/code) installed | No | Calls `claude -p` as a subprocess. No API key or embeddings needed. **Best for getting started.** |
| `anthropic` | `ANTHROPIC_API_KEY` | Keyword index | Prompt caching reduces cost across a batch run |
| `openai` | `OPENAI_API_KEY` | Vector + keyword | Embeddings via `text-embedding-3-small` |
| `ollama` | Ollama running locally | Vector + keyword | Embeddings via `nomic-embed-text`; fully offline, no API key |

RAG (Retrieval-Augmented Generation) is built automatically when the provider supports it. Each document group (pipeline + its linked artifacts) gets its own isolated index so context never crosses document boundaries. Providers that do not support embeddings (`anthropic`, `local`) use a keyword index for retrieval.

---

## Purpose enrichment from tickets and PRs

The **Purpose** section is enriched before the LLM call by searching linked work items and pull requests:

1. **Jira** — searched when `JIRA_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN` are set. Results are filtered to `JIRA_PROJECT_KEY` when provided.
2. **Azure DevOps** — work items and PRs are searched when `AZDO_ORG`, `AZDO_PROJECT`, and `AZDO_PAT` are set (the same variables used for wiki publishing).

When relevant items are found, their titles and descriptions are prepended to the LLM prompt so the generated purpose reflects real business intent. When nothing is found, the artifact's own data flow is used as a fallback context to infer the purpose.

Both backends are optional and independent — configure one, both, or neither.

---

## Prompt customisation

Each section prompt lives in its own file inside the `prompts/` folder. Edit the file for the section you want to change and the next run picks it up — no code changes required. Files absent from the folder fall back to built-in defaults, so partial customisation is safe.

```
prompts/
  system_prompt.md          — writing style and tone for all sections
  lineage_system_prompt.md  — persona and rules for the Column Lineage section
  purpose.md
  flow.md
  business_goal.md
  data_quality.md
  column_lineage.md
```

Within a file you can split the prompt into multiple **sub-prompts** by placing a line containing only `---` between them. The agent makes one LLM call per sub-prompt and joins the results into a single section.

Lines starting with `>` are editorial notes — they are stripped before the prompt is sent to the LLM, so you can annotate files freely.

**Template variables:**

| Variable | Replaced with |
| --- | --- |
| `{{name}}` | Artifact name |
| `{{content}}` | Section-specific content extracted from the source files |
| `{{rag_context}}` | Background context retrieved from the RAG index (empty when RAG is disabled) |

To use a different prompts folder:

```env
PROMPTS_DIR=./my_prompts
```

---

## Company / project context

Point `CONTEXT_FILE` at a plain-text file describing your organisation, domain, or data platform. The content is appended to the system prompt so generated documentation uses your terminology and reflects your business context.

```env
CONTEXT_FILE=./context.txt
```

---

## Source repository

Set `GITHUB_REPO_URL` to have the agent clone a repository before scanning. The clone replaces `./src` and `--src` defaults to the clone root.

```env
GITHUB_REPO_URL=https://github.com/your-org/your-fabric-repo
```

---

## Wiki publishing

Set `PUBLISH_WIKI=true` to push every generated page to a wiki immediately after generation. Pages are created if they do not exist and updated (with ETag version control) if they do. The agent skips generation for any artifact that already has a current wiki page.

Set `WIKI_TYPE` to choose the backend (default: `azuredevops`).

### Azure DevOps

```env
PUBLISH_WIKI=true
WIKI_TYPE=azuredevops
AZDO_ORG=my-organisation
AZDO_PROJECT=my-project
AZDO_WIKI_ID=my-project.wiki
AZDO_PAT=<personal-access-token>
AZDO_WIKI_PATH_PREFIX=/Fabric Docs   # optional — nest pages under this path
```

The PAT needs **Wiki (Read & Write)** scope.

### Confluence

```env
PUBLISH_WIKI=true
WIKI_TYPE=confluence
CONFLUENCE_URL=https://mycompany.atlassian.net
CONFLUENCE_SPACE_KEY=FABRIC
CONFLUENCE_EMAIL=user@example.com
CONFLUENCE_API_TOKEN=<api-token>
CONFLUENCE_PARENT_PAGE_ID=           # optional — nest pages under this ID
```

Markdown is converted to Confluence storage format (XHTML) before upload.

---

## Configuration reference

All settings are read from `.env`. See `.env.example` for the full list with comments.

### LLM

| Variable | Default | Description |
| --- | --- | --- |
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `openai`, `ollama`, or `local` |
| `LLM_MODEL` | provider default | Override the model name (`claude-sonnet-4-6` / `gpt-4o-mini` / `llama3.2`) |
| `ANTHROPIC_API_KEY` | — | Required for `anthropic` |
| `OPENAI_API_KEY` | — | Required for `openai` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Only for `ollama` |
| `EMBEDDING_MODEL` | provider default | Override the embedding model used for RAG |

### Input / output

| Variable | Default | Description |
| --- | --- | --- |
| `ARTIFACT_TYPES` | `pipeline,notebook,dataflow` | Comma-separated list of artifact types to scan. Add `powerautomate` to include Power Automate flows. |
| `GITHUB_REPO_URL` | — | Git repository to clone into `./src` before scanning |
| `OUTPUT_DIR` | `./output` | Directory where `.md` files are written |
| `CONTEXT_FILE` | — | Plain-text file with organisation / domain context |
| `PROMPTS_DIR` | `./prompts` | Folder of per-section prompt files (`{key}.md`) |

### Purpose enrichment

| Variable | Default | Description |
| --- | --- | --- |
| `JIRA_URL` | — | Jira base URL (e.g. `https://mycompany.atlassian.net`) |
| `JIRA_EMAIL` | — | Jira user email |
| `JIRA_API_TOKEN` | — | Jira API token |
| `JIRA_PROJECT_KEY` | — | Optional — restrict Jira search to this project key |

Azure DevOps work items and PRs are searched automatically when `AZDO_ORG`, `AZDO_PROJECT`, and `AZDO_PAT` are set (see wiki publishing variables below).

### Wiki publishing

| Variable | Default | Description |
| --- | --- | --- |
| `PUBLISH_WIKI` | `false` | Set to `true`, `1`, or `yes` to enable |
| `WIKI_TYPE` | `azuredevops` | `azuredevops` or `confluence` |
| `AZDO_ORG` | — | Azure DevOps organisation name |
| `AZDO_PROJECT` | — | Azure DevOps project name |
| `AZDO_WIKI_ID` | — | Wiki identifier as shown in the URL |
| `AZDO_PAT` | — | Personal Access Token (Wiki Read & Write scope) |
| `AZDO_WIKI_PATH_PREFIX` | — | Optional page path prefix, e.g. `/Fabric Docs` |
| `CONFLUENCE_URL` | — | Confluence base URL |
| `CONFLUENCE_SPACE_KEY` | — | Target space key |
| `CONFLUENCE_EMAIL` | — | Confluence user email |
| `CONFLUENCE_API_TOKEN` | — | Confluence API token |
| `CONFLUENCE_PARENT_PAGE_ID` | — | Optional parent page ID |

---

## Project structure

```
agent/
  ai/               LLM clients — Anthropic, OpenAI, Ollama, local Claude CLI
  enrichers/        Purpose enrichment — Jira and Azure DevOps ticket/PR lookup
  generators/       Document assembly — one LLM call per section, results joined
  parsers/          Source parsers — pipeline JSON, notebook .ipynb, Dataflow Gen2, Power Automate
    base_parser.py        Abstract ArtifactParser base class
    parser_registry.py    Dependency-injection registry; add new types here
    pipeline_parser.py
    notebook_parser.py
    dataflow_parser.py
    powerautomate_parser.py
  publishers/       Wiki publishers — Azure DevOps and Confluence backends
  rag/              RAG index — keyword (all providers) and vector (OpenAI/Ollama)
  config.py         Environment variable loading (including ARTIFACT_TYPES)
  main.py           CLI entry point
prompts.md          Per-section prompt templates (edit to customise output)
samples/            Example source files and generated output
tests/              pytest suite (361 tests)
```

---

## Running the tests

```bash
uv run pytest

# Or with plain pytest
pytest
```

---

## License

Apache 2.0
