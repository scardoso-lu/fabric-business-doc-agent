"""
Two index types, both always available:

1. Keyword index  — dict[group_id, list[str]]; works with every provider;
                    built first, used as guaranteed fallback.
2. Vector index   — in-memory Qdrant; requires OpenAI or Ollama embeddings;
                    used when available for better semantic retrieval.

Items are grouped by doc_group so retrieval is scoped to a single unit:
  - pipeline + linked notebooks → group_id = pipeline name
  - orphan notebook             → group_id = notebook name
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from agent.config import ACTIVITY_TYPE_LABELS, BRONZE_ACTIVITY_TYPES, DATAFLOW_ACTIVITY_TYPES, SILVER_ACTIVITY_TYPES
from agent.parsers.dataflow_parser import ParsedDataflow
from agent.parsers.notebook_parser import ParsedNotebook
from agent.parsers.pipeline_parser import ParsedPipeline, PipelineActivity

if TYPE_CHECKING:
    from agent.ai.llm_client import LLMClient

COLLECTION = "fabric_docs"


@dataclass
class DocGroup:
    group_id: str
    pipeline: ParsedPipeline | None
    notebooks: list[ParsedNotebook] = field(default_factory=list)
    dataflows: list[ParsedDataflow] = field(default_factory=list)


def build_keyword_index(doc_groups: list[DocGroup]) -> dict[str, list[str]]:
    """Build a plain keyword index — no embeddings needed, works with all providers."""
    index: dict[str, list[str]] = {}
    documents: list[str] = []
    metadatas: list[dict] = []

    for group in doc_groups:
        if group.pipeline:
            _add_pipeline_chunks(group, documents, metadatas)
        for notebook in group.notebooks:
            _add_notebook_chunks(group.group_id, notebook, documents, metadatas)
        for dataflow in group.dataflows:
            _add_dataflow_chunks(group.group_id, dataflow, documents, metadatas)

    for doc, meta in zip(documents, metadatas):
        group_id = meta["doc_group"]
        index.setdefault(group_id, []).append(doc)

    return index


def build_vector_index(doc_groups: list[DocGroup], llm_client: LLMClient) -> QdrantClient | None:
    """Embed all chunks via the provider's embeddings API and load into Qdrant.

    Returns None when embeddings are unavailable or the call fails.
    """
    if llm_client.embedding_model is None:
        return None

    documents: list[str] = []
    metadatas: list[dict] = []

    for group in doc_groups:
        if group.pipeline:
            _add_pipeline_chunks(group, documents, metadatas)
        for notebook in group.notebooks:
            _add_notebook_chunks(group.group_id, notebook, documents, metadatas)
        for dataflow in group.dataflows:
            _add_dataflow_chunks(group.group_id, dataflow, documents, metadatas)

    if not documents:
        return None

    vectors = llm_client.embed(documents)
    if not vectors or len(vectors) == 0:
        return None

    dim = len(vectors[0])
    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )
    client.upsert(
        collection_name=COLLECTION,
        points=[
            PointStruct(id=i, vector=vec, payload={"text": doc, **meta})
            for i, (vec, doc, meta) in enumerate(zip(vectors, documents, metadatas))
        ],
    )
    return client


# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------

def _add_pipeline_chunks(
    group: DocGroup,
    documents: list[str],
    metadatas: list[dict],
) -> None:
    pipeline = group.pipeline
    activity_names = [a.name for a in pipeline.activities]

    documents.append(_sanitize(
        f"Pipeline: {pipeline.name}\n"
        f"Description: {pipeline.description or '(none)'}\n"
        f"Activities: {', '.join(activity_names)}"
    ))
    metadatas.append({
        "doc_group": group.group_id,
        "type": "pipeline_overview",
        "name": pipeline.name,
    })

    for activity in pipeline.activities:
        layer = _activity_layer(activity)
        type_label = ACTIVITY_TYPE_LABELS.get(activity.activity_type, activity.activity_type)
        props_text = _props_text(activity.type_properties)
        documents.append(_sanitize(
            f"Activity: {activity.name}\n"
            f"Type: {type_label}\n"
            f"Layer: {layer}\n"
            f"Description: {activity.description or '(none)'}\n"
            f"Properties: {props_text}"
        ))
        metadatas.append({
            "doc_group": group.group_id,
            "type": "pipeline_activity",
            "name": activity.name,
            "layer": layer,
        })


def _add_notebook_chunks(
    group_id: str,
    notebook: ParsedNotebook,
    documents: list[str],
    metadatas: list[dict],
) -> None:
    for section in notebook.sections:
        code = section.combined_code
        markdown_ctx = " ".join(c.source for c in section.markdown_cells)
        parts = [f"Notebook: {notebook.name}", f"Section: {section.heading}"]
        if markdown_ctx.strip():
            parts.append(f"Context: {markdown_ctx[:500]}")
        if code.strip():
            parts.append(f"Code: {code[:800]}")
        documents.append(_sanitize("\n".join(parts)))
        metadatas.append({
            "doc_group": group_id,
            "type": "notebook_section",
            "name": f"{notebook.name} / {section.heading}",
            "notebook_name": notebook.name,
        })


def _add_dataflow_chunks(
    group_id: str,
    dataflow: ParsedDataflow,
    documents: list[str],
    metadatas: list[dict],
) -> None:
    documents.append(_sanitize(
        f"Dataflow: {dataflow.name}\n"
        f"Description: {dataflow.description or '(none)'}\n"
        f"Queries: {', '.join(dataflow.query_names)}"
    ))
    metadatas.append({
        "doc_group": group_id,
        "type": "dataflow_overview",
        "name": dataflow.name,
    })
    for query in dataflow.queries:
        documents.append(_sanitize(
            f"Dataflow: {dataflow.name}\n"
            f"Query: {query.name}\n"
            f"Description: {query.description or '(none)'}\n"
            f"M-code: {query.pq_code[:800]}"
        ))
        metadatas.append({
            "doc_group": group_id,
            "type": "dataflow_query",
            "name": f"{dataflow.name} / {query.name}",
            "dataflow_name": dataflow.name,
        })


def _activity_layer(activity: PipelineActivity) -> str:
    if activity.activity_type in BRONZE_ACTIVITY_TYPES:
        return "bronze"
    if activity.activity_type in SILVER_ACTIVITY_TYPES:
        return "silver"
    if activity.activity_type in DATAFLOW_ACTIVITY_TYPES:
        return "gold"
    return "control"


def _props_text(props: dict) -> str:
    if not props:
        return "(none)"
    parts = [f"{k}: {str(v)[:80]}" for k, v in props.items() if not isinstance(v, (dict, list))]
    return ", ".join(parts) or "(none)"


_INSTRUCTION_PATTERNS = (
    "return the", "write a", "document this", "describe this",
    "do not", "do not reproduce", "return only", "note:", "(note:",
    "%%", "rerun", "you'll need",
)


def _sanitize(text: str) -> str:
    """Strip lines that look like LLM instructions or notebook meta-comments."""
    clean = []
    for line in text.splitlines():
        lower = line.strip().lower()
        if any(lower.startswith(p) for p in _INSTRUCTION_PATTERNS):
            continue
        if lower.startswith("```") or lower.startswith("~~~"):
            continue
        clean.append(line)
    return "\n".join(clean).strip()
