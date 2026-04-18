# Fabric Business Documentation Agent

Automatically generates plain-English business documentation from Microsoft Fabric pipelines and notebooks using an LLM. Each artifact becomes a structured markdown page covering its purpose, behaviour, data flow (with a Mermaid diagram), business goal, and data quality rules — ready to publish to an Azure DevOps or Confluence wiki.

---

## What it produces

For every pipeline JSON and notebook `.ipynb` file found under the source directory, the agent writes a markdown file with five sections:

| Section | Content |
| --- | --- |
| **Purpose** | Why this process exists and what business need it serves |
| **Flow** | Data flow in prose and a Mermaid `flowchart LR` diagram |
| **Business Goal** | Outcome delivered and what breaks if it stops running |
| **Data Quality & Alerts** | Validation checks, conditions, and failure paths |

Example output is in [`samples/`](samples/).

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

Copy `.env.example` to `.env` and fill in the values for your chosen LLM provider.

```bash
cp .env.example .env
```

### 3. Run

```bash
# Document everything under ./src
python -m agent.main --src ./src

# Pipelines only, notebooks only, or filter by name
python -m agent.main --src ./src --pipelines-only
python -m agent.main --src ./src --notebooks-only
python -m agent.main --src ./src --pipeline "MyPipeline"
python -m agent.main --src ./src --notebook "MyNotebook"

# Write output to a custom directory
python -m agent.main --src ./src --output ./docs
```

Windows users can use the convenience wrapper:

```bat
run.bat [src_dir] [output_dir]
```

---

## LLM providers

Select a provider by setting `LLM_PROVIDER` in `.env`.

| `LLM_PROVIDER` | Requires | RAG | Notes |
| --- | --- | --- | --- |
| `local` | Claude CLI installed | No | Calls `claude -p` subprocess — no API key or embeddings needed. **Recommended for getting started.** |
| `anthropic` | `ANTHROPIC_API_KEY` | Keyword index | Prompt caching reduces cost across a run |
| `openai` | `OPENAI_API_KEY` | Vector + keyword | Embeddings via `text-embedding-3-small` |
| `ollama` | Ollama running locally | Vector + keyword | Embeddings via `nomic-embed-text`; no API key |

The `local` provider uses the [Claude CLI](https://claude.ai/code) already installed on your machine. No external API key or embedding service is needed — the agent passes each artifact's content directly to Claude as a prompt.

---

## Prompt customisation (optional)

Every section prompt is defined in `prompts.md` at the project root. Open the file, edit any `## section_key` block, and the next run will use your version. Sections you leave unchanged keep their built-in defaults.

Available keys: `system_prompt`, `lineage_system_prompt`, `purpose`, `flow`, `business_goal`, `data_quality`, `column_lineage`.

Template variables you can use in any prompt: `{{name}}` (artifact name), `{{content}}` (extracted source data), `{{rag_context}}` (RAG background context).

To use a different file, set `PROMPTS_FILE` in `.env`:

```env
PROMPTS_FILE=./my_prompts.md
```

---

## Company / project context (optional)

Point `CONTEXT_FILE` at a plain-text file describing your organisation, domain, or project. The agent appends its contents to the system prompt so the generated documentation reflects your specific terminology and business context.

```env
CONTEXT_FILE=./context.txt
```

---

## Source repository (optional)

Set `GITHUB_REPO_URL` to have the agent clone a repository before scanning. When set, `--src` defaults to the clone root.

```env
GITHUB_REPO_URL=https://github.com/your-org/your-fabric-repo
```

---

## Wiki publishing (optional)

Set `PUBLISH_WIKI=true` in `.env` to push every generated page to a wiki after generation. Pages are created if they do not exist, or updated if they do. The agent skips generation entirely for any artifact that already has a wiki page.

Set `WIKI_TYPE` to choose the backend (default: `azuredevops`).

### Azure DevOps

```env
PUBLISH_WIKI=true
WIKI_TYPE=azuredevops
AZDO_ORG=my-organisation
AZDO_PROJECT=my-project
AZDO_WIKI_ID=my-project.wiki
AZDO_PAT=<personal-access-token>
AZDO_WIKI_PATH_PREFIX=/Fabric Docs   # optional
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
CONFLUENCE_PARENT_PAGE_ID=           # optional: nest pages under this ID
```

Markdown is converted to Confluence storage format (XHTML) before upload.

---

## Configuration reference

All settings are read from `.env`. See `.env.example` for the full list with comments.

| Variable | Default | Description |
| --- | --- | --- |
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `openai`, `ollama`, or `local` |
| `LLM_MODEL` | provider default | Override the model name |
| `ANTHROPIC_API_KEY` | — | Required for `anthropic` |
| `OPENAI_API_KEY` | — | Required for `openai` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Only for `ollama` |
| `EMBEDDING_MODEL` | provider default | Override the embedding model |
| `GITHUB_REPO_URL` | — | Repo to clone before scanning |
| `OUTPUT_DIR` | `./output` | Directory for generated `.md` files |
| `CONTEXT_FILE` | — | Path to a plain-text context file |
| `PUBLISH_WIKI` | `false` | Set to `true` to enable wiki publishing |
| `WIKI_TYPE` | `azuredevops` | `azuredevops` or `confluence` |
| `AZDO_ORG` | — | Azure DevOps organisation name |
| `AZDO_PROJECT` | — | Azure DevOps project name |
| `AZDO_WIKI_ID` | — | Wiki identifier (as shown in the URL) |
| `AZDO_PAT` | — | Personal Access Token |
| `AZDO_WIKI_PATH_PREFIX` | — | Optional page path prefix |
| `CONFLUENCE_URL` | — | Confluence base URL |
| `CONFLUENCE_SPACE_KEY` | — | Target space key |
| `CONFLUENCE_EMAIL` | — | User email |
| `CONFLUENCE_API_TOKEN` | — | API token |
| `CONFLUENCE_PARENT_PAGE_ID` | — | Optional parent page ID |

---

## Project structure

```
agent/
  ai/               LLM client implementations (Anthropic, OpenAI, Ollama, local Claude)
  generators/       Documentation generation logic (one LLM call per section)
  parsers/          Pipeline JSON and notebook .ipynb parsers
  publishers/       Wiki publisher implementations (Azure DevOps, Confluence)
  rag/              Keyword and vector index for RAG-enabled providers
  config.py         Environment variable loading
  main.py           CLI entry point
samples/            Example pipeline and notebook source files
tests/              pytest test suite (189 tests)
```

---

## Running the tests

```bash
pytest
```

---

## License

Apache 2.0
