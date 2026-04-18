import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
ROOT_DIR = Path(__file__).parent.parent
SRC_DIR = ROOT_DIR / "src"
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(ROOT_DIR / "output")))

# LLM provider — anthropic | openai | ollama
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
# Model name — leave blank to use the provider default
LLM_MODEL = os.getenv("LLM_MODEL", "")
# Ollama base URL (only used when LLM_PROVIDER=ollama)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# Embedding model for RAG — defaults per provider:
#   openai  → text-embedding-3-small
#   ollama  → nomic-embed-text
#   anthropic → (no embeddings API; RAG is skipped)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "")
# GitHub repository to clone before scanning (optional)
GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL", "")
# Push generated docs to Azure DevOps wiki — set to "true" to enable
PUBLISH_WIKI = os.getenv("PUBLISH_WIKI", "").lower() in ("1", "true", "yes")
# Path to a plain-text file with company/project context (optional)
# Content is appended to the system prompt to improve documentation quality.
CONTEXT_FILE = os.getenv("CONTEXT_FILE", "")
# Directory containing per-section prompt files ({key}.md).
# Defaults to the prompts/ folder in the project root.
# Set PROMPTS_DIR to a custom path to use a different folder.
PROMPTS_DIR = Path(os.getenv("PROMPTS_DIR", str(ROOT_DIR / "prompts")))
# Artifact types to scan — comma-separated list.
# Supported values: pipeline, notebook, dataflow, powerautomate
# Default omits powerautomate so existing repos are not affected.
# Set ARTIFACT_TYPES=pipeline,notebook,dataflow,powerautomate to enable all.
_raw_artifact_types = os.getenv("ARTIFACT_TYPES", "pipeline,notebook,dataflow")
ARTIFACT_TYPES: list[str] = [t.strip().lower() for t in _raw_artifact_types.split(",") if t.strip()]

CONTEXT_TEXT: str = ""
if CONTEXT_FILE:
    try:
        CONTEXT_TEXT = Path(CONTEXT_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        pass  # main.py warns the user when CONTEXT_FILE is set but unreadable

# Medallion layer classification
# Bronze — raw ingestion activities (bring data in from external sources)
BRONZE_ACTIVITY_TYPES = {
    "Copy", "Web", "WebHook", "GetMetadata", "Lookup", "Delete",
}
# Silver — transformation activities (clean, enrich, apply business logic)
SILVER_ACTIVITY_TYPES = {
    "TridentNotebook", "Notebook", "Script",
}
# Gold — dataflow activities (Power Query transformations producing final tables)
DATAFLOW_ACTIVITY_TYPES = {
    "ExecuteDataflow", "Dataflow",
}
# Control-flow activities — not assigned to a layer
CONTROL_ACTIVITY_TYPES = {
    "IfCondition", "ForEach", "Until", "Switch",
    "SetVariable", "Append", "Wait", "ExecutePipeline", "Fail", "Filter",
}

# Fabric pipeline activity types → human-readable labels
ACTIVITY_TYPE_LABELS = {
    "TridentNotebook":  "Run Notebook",
    "Copy":             "Copy Data",
    "ForEach":          "Repeat for Each Item",
    "IfCondition":      "Decision / Branch",
    "ExecutePipeline":  "Run Sub-Pipeline",
    "SetVariable":      "Set Value",
    "Wait":             "Wait / Pause",
    "Web":              "Call External Service",
    "WebHook":          "Wait for External Signal",
    "Lookup":           "Look Up Data",
    "GetMetadata":      "Inspect File / Table Info",
    "Delete":           "Delete Files",
    "Script":           "Run SQL Script",
    "ExecuteDataflow":  "Run Dataflow",
    "Dataflow":         "Run Dataflow",
    "Fail":             "Raise Error",
    "Filter":           "Filter Items",
    "Until":            "Repeat Until Condition",
    "Switch":           "Multi-way Decision",
    "Append":           "Add to List",
}

# Dependency condition labels
DEPENDENCY_CONDITION_LABELS = {
    "Succeeded": "only if the previous step succeeded",
    "Failed":    "only if the previous step failed",
    "Skipped":   "only if the previous step was skipped",
    "Completed": "regardless of whether the previous step succeeded or failed",
}
