"""
mermaid_pipeline_diagram.py

Purpose
-------
Generate Mermaid flowchart diagrams for BookieX pipeline and agentic work.
Run from project root:  python tools/mermaid_pipeline_diagram.py

Output
------
- tools/pipeline_diagram.md — plain Markdown with mermaid blocks.
- tools/pipeline_diagram_collapsible.md — same content with <details> wrappers
  for copy-paste into README or wiki.
"""

from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
OUTPUT_PATH = SCRIPT_DIR / "pipeline_diagram.md"
OUTPUT_COLLAPSIBLE_PATH = SCRIPT_DIR / "pipeline_diagram_collapsible.md"


NCAAM_DAILY_FLOW = """
%% NCAAM Daily View & Dashboard (agentic work)
flowchart LR
    subgraph Ingest
        A[Schedule raw] --> B[Schedule mapped]
        C[Odds raw] --> D[Odds flat / team map]
    end
    subgraph Canonical
        B --> E[Canonical games]
        D --> F[Games with lines]
        E --> F
    end
    subgraph Model
        F --> G[Model features]
        G --> H[ncaam_games_multi_model_v1.json]
    end
    subgraph Daily
        H --> I[build_daily_view_ncaam.py]
        I --> J["daily_view_ncaam_YYYY-MM-DD_v1.json"]
        I --> K[timestamped CSV]
    end
    subgraph Consume
        J --> L[bookiex_dashboard.py]
        L --> M[Streamlit UI]
    end
    subgraph Deploy
        J --> N[push_daily.py]
        N --> O[git add data/ncaam/daily/]
        O --> P[commit & push]
    end
"""

DASHBOARD_FILE_PICK = """
%% Dashboard: which file is loaded (latest mtime per date)
flowchart TD
    subgraph Input
        F[DAILY_DIR glob]
    end
    subgraph Logic
        F --> G[Group by date]
        G --> H[Per date: max by st_mtime]
        H --> I[date_map date -> Path]
    end
    subgraph Output
        I --> J[Select date in UI]
        J --> K["Load date_map[selected_date]"]
        K --> L["print(Loading: path)"]
        L --> M[Show Last Odds Update from JSON]
    end
"""

PIPELINE_OVERVIEW = """
%% BookieX pipeline overview
flowchart TB
    subgraph Data
        D1[Raw schedule & odds]
        D2[Canonical games]
        D3[Game-level with lines]
    end
    subgraph Features
        D3 --> F1[Avg score / momentum]
        F1 --> F2[Multi-model merge]
    end
    subgraph Outputs
        F2 --> O1[final_game_view]
        F2 --> O2[build_daily_view_ncaam]
        O2 --> O3[daily JSON + CSV]
    end
    subgraph UI
        O3 --> U1[Dashboard]
        U1 --> U2[Last Odds Update from JSON]
    end
    D1 --> D2
"""


def main():
    blocks = [
        ("# BookieX pipeline diagrams", ""),
        ("## NCAAM daily view flow", "```mermaid" + NCAAM_DAILY_FLOW + "```"),
        ("## Dashboard file selection (latest per date)", "```mermaid" + DASHBOARD_FILE_PICK + "```"),
        ("## Pipeline overview", "```mermaid" + PIPELINE_OVERVIEW + "```"),
    ]
    lines = []
    for title, body in blocks:
        lines.append(title)
        lines.append("")
        lines.append(body.strip())
        lines.append("")
    content = "\n".join(lines).strip() + "\n"
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote: {OUTPUT_PATH}")

    # Collapsible version for README/wiki: each diagram in a <details> block.
    collapsible_blocks = [
        ("NCAAM daily view flow", "```mermaid" + NCAAM_DAILY_FLOW + "```"),
        ("Dashboard file selection (latest per date)", "```mermaid" + DASHBOARD_FILE_PICK + "```"),
        ("Pipeline overview", "```mermaid" + PIPELINE_OVERVIEW + "```"),
    ]
    collapsible_lines = ["# BookieX pipeline diagrams", "", "Copy-paste into README or wiki.", ""]
    for summary, body in collapsible_blocks:
        collapsible_lines.append("<details>")
        collapsible_lines.append(f"<summary>{summary}</summary>")
        collapsible_lines.append("")
        collapsible_lines.append(body.strip())
        collapsible_lines.append("")
        collapsible_lines.append("</details>")
        collapsible_lines.append("")
    collapsible_content = "\n".join(collapsible_lines).strip() + "\n"
    OUTPUT_COLLAPSIBLE_PATH.write_text(collapsible_content, encoding="utf-8")
    print(f"Wrote: {OUTPUT_COLLAPSIBLE_PATH}")
    print("Open in Cursor or paste into GitHub/Notion README.")


if __name__ == "__main__":
    main()
