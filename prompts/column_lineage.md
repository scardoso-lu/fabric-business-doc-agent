> Section: Column Lineage — column-by-column mapping from bronze source to gold output.
> Single sub-prompt. Uses the lineage_system_prompt persona (not the default system prompt).
> Returns Markdown tables (one per layer pair) or the fixed string
> "No column lineage detected in this artifact." when no explicit transforms are found.
> Only persistent tables are documented — see lineage_system_prompt.md for the full scope rules.

Extract column-level data lineage for "{{name}}".

Only trace tables that are written to persistent storage — the data lake, lakehouse, or data warehouse. Work backwards from the gold (final persisted output) through silver to bronze (raw source).

Skip temporary objects: any table or query whose name starts with #, tmp_, or temp_; any SQL @variable or CTE; any intermediate DataFrame or M-code query that is never written to a destination. If a layer contains only temporary objects, omit that layer entirely from the output.

Produce one table per layer pair (e.g., Silver → Gold, Bronze → Silver). Describe the transformation applied to each column in plain English.

Code and schema information:
{{content}}
