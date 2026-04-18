"""Shared factory helpers used across the test suite."""

from pathlib import Path

from agent.parsers.dataflow_parser import DataflowQuery, ParsedDataflow
from agent.parsers.notebook_parser import NotebookCell, NotebookSection, ParsedNotebook
from agent.parsers.pipeline_parser import (
    ActivityDependency,
    PipelineActivity,
    PipelineParameter,
    ParsedPipeline,
)


def make_activity(
    name: str = "LoadData",
    activity_type: str = "Copy",
    depends_on: list | None = None,
    type_properties: dict | None = None,
    description: str = "",
) -> PipelineActivity:
    return PipelineActivity(
        name=name,
        activity_type=activity_type,
        description=description,
        depends_on=depends_on or [],
        type_properties=type_properties or {},
        raw={},
    )


def make_pipeline(
    name: str = "TestPipeline",
    activities: list | None = None,
    description: str = "A test pipeline",
    path: Path | None = None,
    parameters: list | None = None,
) -> ParsedPipeline:
    return ParsedPipeline(
        name=name,
        description=description,
        source_path=path or Path(f"{name}.json"),
        parameters=parameters or [],
        activities=activities or [],
    )


def make_dataflow_query(
    name: str = "SalesQuery",
    pq_code: str = 'let\n    Source = Sql.Database("server", "db")\nin\n    Source',
    description: str = "",
) -> DataflowQuery:
    return DataflowQuery(name=name, pq_code=pq_code, description=description)


def make_dataflow(
    name: str = "TestDataflow",
    queries: list | None = None,
    description: str = "A test dataflow",
    path: Path | None = None,
) -> ParsedDataflow:
    return ParsedDataflow(
        name=name,
        source_path=path or Path(f"{name}.json"),
        description=description,
        queries=queries or [make_dataflow_query()],
    )


def make_notebook_section(heading: str = "Overview", code: str = "") -> NotebookSection:
    cells = []
    if code:
        cells.append(NotebookCell(cell_type="code", source=code, cell_index=0))
    return NotebookSection(heading=heading, cells=cells)


def make_notebook(
    name: str = "TestNotebook",
    sections: list | None = None,
    description: str = "A test notebook",
    path: Path | None = None,
) -> ParsedNotebook:
    return ParsedNotebook(
        name=name,
        source_path=path or Path(f"{name}.ipynb"),
        description=description,
        sections=sections or [make_notebook_section()],
        language="python",
    )
