# ACH Reconciliation Flow

This project is an LLM-driven ACH reconciliation agent. The code does not hard-code matching rules; it loads raw AR and bank data, lets the model reason over the records, records decisions in batches, and then writes an Excel reconciliation report.

```mermaid
flowchart TD
    A["Start: python main.py"] --> B["Load .env"]
    B --> C{"ANTHROPIC_API_KEY present?"}

    C -- No --> C1["Print error and exit"]
    C -- Yes --> D["Parse CLI args"]

    D --> E{"Input file exists?"}

    E -- No --> E1["Print error and exit"]
    E -- Yes --> F["Create ACHReconAgent"]

    F --> G["ACHReconAgent.run()"]

    G --> H["Build user request with file path and output dir"]

    H --> I["Detect LLM provider"]

    I --> J{"Azure env vars set?"}

    J -- Yes --> J1["Use Azure OpenAI"]
    J -- No --> J2["Use Anthropic"]

    J1 --> K["Create message loop"]
    J2 --> K

    K --> L["Call LLM with system prompt + tool schema + history"]

    L --> M{"LLM stop_reason"}

    M -- tool_use --> N["Execute tool calls"]
    M -- end_turn --> Z["Finish and return final result"]
    M -- other --> Y["Print unexpected stop_reason and stop"]

    N --> N1["initialize(file_path)"]
    N1 --> N2["Read workbook with pandas"]
    N2 --> N3["Load AR sheet"]
    N3 --> N4["Filter AR rows where Type = ACH"]
    N4 --> N5["Load JP sheet"]
    N5 --> N6["Filter JP rows where SubCategory = ACH"]
    N6 --> N7["Load FC sheet"]
    N7 --> N8["Store data in in-memory state"]
    N8 --> N9["Return sheet counts only"]

    N --> O["get_ar_ach_records"]
    O --> O1["Return all AR ACH rows with normalized fields"]

    N --> P["get_bank_records(bank='JP' or 'FC')"]
    P --> P1["Return raw JP ACH rows or raw FC rows"]

    N --> Q["record_decisions(decisions)"]
    Q --> Q1["Validate ar_index"]
    Q1 --> Q2["Append decisions to in-memory state"]
    Q2 --> Q3["Return saved count, total so far, remaining"]

    N --> R["generate_report(output_dir)"]

    R --> R1["Require loaded data and at least one decision"]
    R1 --> R2["Create output directory"]
    R2 --> R3["Build decision_map by AR index"]
    R3 --> R4["write_reconciliation_report(...)"]

    R4 --> S["Excel Writer"]

    S --> S1["Sheet 1: ACH Recon Results"]
    S1 --> S2["Color rows by status"]
    S2 --> S3["Write AR details, status, bank details, reasoning"]

    S3 --> T["Sheet 2: Bank Orphans"]
    T --> T1["List unmatched JP and FC bank records"]

    T1 --> U["Sheet 3: Audit Log"]
    U --> U1["Write run summary, counts, totals, legend"]

    U1 --> V["Save .xlsx report"]

    V --> W["Return output_file + audit_summary"]

    W --> X["Agent prints completion summary"]

    X --> Z

    L --> L1["If response has text, print agent reasoning"]
    L1 --> L2["If response requests tools, loop back after tool results"]

    N9 --> K
    O1 --> K
    P1 --> K
    Q3 --> K
    W --> K

```

# Overview Diagram

```mermaid

flowchart TD

    A["Start: python main.py"] --> B["Load environment and validate input file"]

    B --> C["Create ACHReconAgent"]

    C --> D["Start LLM-driven reconciliation loop"]

    D --> E["initialize file and load workbook"]

    E --> F["Load AR ACH rows"]
    E --> G["Load JP ACH rows"]
    E --> H["Load FC bank rows"]

    F --> I["Agent reviews raw AR records"]
    G --> J["Agent reviews JP bank records"]
    H --> K["Agent reviews FC bank records"]

    I --> L["LLM compares AR and bank data"]
    J --> L
    K --> L

    L --> M{"For every AR record"}

    M --> N["Classify as MATCHED, PARTIAL, or UNMATCHED"]

    N --> O["Submit decisions in batches"]

    O --> P["Accumulate decisions in memory"]

    P --> Q{"All AR records decided?"}

    Q -- No --> L

    Q -- Yes --> R["Generate final report"]

    R --> S["Write ACH Recon Results sheet"]
    R --> T["Write Bank Orphans sheet"]
    R --> U["Write Audit Log sheet"]

    S --> V["Save Excel file"]
    T --> V
    U --> V

    V --> W["Return output path and audit summary"]

    W --> X["Print completion summary"]