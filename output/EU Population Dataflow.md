# EU Population Dataflow

| | |
| --- | --- |
| **Type** | Dataflow Gen2 |
| **Source file** | `eu_population_dataflow.json` |
| **Generated** | 2026-04-18 |


## Purpose

Insufficient information available.

Insufficient information available.

## Flow

The EU Population Dataflow pulls raw population statistics directly from the Eurostat public website. Initially, the process fetches every available data point as-is, without applying any rules or changes. Next, the system cleans and refines this raw data. It removes incomplete records and separates complex data keys into specific Year and Country Code columns. It also converts necessary text and raw value columns into universal number formats (integers) to ensure accurate calculations later on.
The final output, available for reporting, is highly filtered and ready for use. The process restricts the data only to the current EU-27 member states. It also enhances readability by resolving the raw country codes into proper, recognizable country names. This resulting table provides a standardized, clean summary of the most recent European population figures, making it immediately usable for business analysis.

Insufficient information available.

```mermaid
flowchart LR
    Eurostat_API[Eurostat Population API] --> EU_Dataflow[EU Population Dataflow] --> Downstream_Consumer[Reporting Applications]
```

Insufficient information available.

## Business Goal

Insufficient information available.

Insufficient information available.

## Data Quality & Alerts

Insufficient information available.

Insufficient information available.

## Column Lineage

### CleanedPopulation → EUPopulationGold
| Source | Target Column | Transformation Logic |
| :--- | :--- | :--- |
| Year | Year | Pass-through |
| GeoCode | GeoCode | Pass-through |
| Population | Population | Pass-through |
| GeoCode | CountryName | Lookup value based on the Eurostat ISO code (e.g., AT $\to$ Austria) [^1] |

**Note 1:** The `CountryName` column is derived by looking up the two-letter country code (`GeoCode`) against a predefined mapping table (e.g., AT maps to Austria).

### RawEurostatData → CleanedPopulation
| Source | Target Column | Transformation Logic |
| :--- | :--- | :--- |
| RecordKey | Year | Extracted segment of the `RecordKey` delimited by ':' (The year) |
| RecordKey | GeoCode | Extracted segment of the `RecordKey` delimited by ':' (The Geo Code) |
| RawValue | Population | Pass-through, then cast to Integer type [^2] |

**Note 2:** The `RawValue` column is renamed to `Population` and cast to Integer type. Empty or null rows from `RawValue` are filtered out.


---

*Documentation generated on 2026-04-18 from `eu_population_dataflow.json`.*