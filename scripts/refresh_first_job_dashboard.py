#!/usr/bin/env python3
"""Refresh the first-job dashboard from the latest available input file."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import first_job_graphs as fjg


ROOT = Path(__file__).resolve().parents[1]
CODEX_DATA = ROOT / "codex_data"
OUTPUT_DIR = ROOT / "outputs" / "first_job_graphs"
DOCS_DIR = ROOT / "docs"
METADATA_PATH = OUTPUT_DIR / "refresh_metadata.json"
SUMMARY_PATH = OUTPUT_DIR / "refresh_metadata.md"

CANONICAL_BASENAME = "first_job_after_phd_classified"
REQUIRED_COLUMNS = [
    "grad_year",
    "nsf_broad",
    "nsf_major",
    "first_job_org_type",
    "classification_source",
]
ORG_NAME_COLUMNS = [
    "revelio_primary_name",
    "revelio_company",
    "ultimate_parent_rcid_name",
    "company_raw",
    "company_cleaned",
]


def detect_input_file() -> Path:
    preferred = CODEX_DATA / f"{CANONICAL_BASENAME}.csv"
    if preferred.exists():
        return preferred

    candidates = sorted(
        [
            path
            for path in CODEX_DATA.iterdir()
            if path.is_file()
            and path.suffix.lower() in {".csv", ".parquet"}
            and "first_job_after_phd" in path.name.lower()
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            "No first-job input file found in codex_data. Expected a CSV or Parquet with "
            "'first_job_after_phd' in the filename."
        )
    return candidates[0]


def validate_csv(path: Path) -> Dict[str, object]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"{path.name} has no header row.")

        missing = [col for col in REQUIRED_COLUMNS if col not in reader.fieldnames]
        if missing:
            raise ValueError(f"{path.name} is missing required columns: {', '.join(missing)}")

        if not any(col in reader.fieldnames for col in ORG_NAME_COLUMNS):
            raise ValueError(
                f"{path.name} must include at least one employer-name column: "
                + ", ".join(ORG_NAME_COLUMNS)
            )

        row_count = 0
        min_year = None
        max_year = None
        nonempty_broad = 0
        nonempty_major = 0
        sample_rows: List[Dict[str, str]] = []

        for row in reader:
            row_count += 1
            if len(sample_rows) < 3:
                sample_rows.append(
                    {
                        "grad_year": row.get("grad_year", ""),
                        "nsf_broad": row.get("nsf_broad", ""),
                        "nsf_major": row.get("nsf_major", ""),
                        "company_raw": row.get("company_raw", ""),
                    }
                )

            grad_year = (row.get("grad_year") or "").strip()
            if grad_year:
                try:
                    year = int(float(grad_year))
                except ValueError as exc:
                    raise ValueError(f"Unparseable grad_year '{grad_year}' in {path.name}") from exc
                min_year = year if min_year is None or year < min_year else min_year
                max_year = year if max_year is None or year > max_year else max_year

            if (row.get("nsf_broad") or "").strip():
                nonempty_broad += 1
            if (row.get("nsf_major") or "").strip():
                nonempty_major += 1

    if row_count == 0:
        raise ValueError(f"{path.name} contains no data rows.")
    if min_year is None or max_year is None:
        raise ValueError(f"{path.name} does not contain any parseable grad_year values.")

    return {
        "row_count": row_count,
        "min_grad_year": min_year,
        "max_grad_year": max_year,
        "nonempty_nsf_broad_rows": nonempty_broad,
        "nonempty_nsf_major_rows": nonempty_major,
        "sample_rows": sample_rows,
        "columns": reader.fieldnames,
    }


def write_metadata(input_path: Path, validation: Dict[str, object]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = sorted(
        p.name for p in OUTPUT_DIR.iterdir() if p.is_file() and not p.name.startswith(".")
    )
    metadata = {
        "refresh_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "input_file": str(input_path),
        "input_basename": input_path.name,
        "override_config": str(ROOT / "config" / "first_job_overrides.json"),
        "input_size_bytes": input_path.stat().st_size,
        "input_modified_utc": datetime.fromtimestamp(
            input_path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
        "validation": validation,
        "outputs": outputs,
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    summary = [
        "# First-Job Dashboard Refresh",
        "",
        f"- Refresh time (UTC): `{metadata['refresh_timestamp_utc']}`",
        f"- Input file: `{input_path.name}`",
        f"- Override config: `config/first_job_overrides.json`",
        f"- Input modified (UTC): `{metadata['input_modified_utc']}`",
        f"- Rows: `{validation['row_count']}`",
        f"- Graduation year range: `{validation['min_grad_year']}` to `{validation['max_grad_year']}`",
        f"- Nonempty `nsf_broad` rows: `{validation['nonempty_nsf_broad_rows']}`",
        f"- Nonempty `nsf_major` rows: `{validation['nonempty_nsf_major_rows']}`",
        "",
        "## Outputs",
    ]
    summary.extend(f"- `{name}`" for name in outputs)
    summary.extend(
        [
            "",
            "## How To Refresh Again",
            "",
            "```bash",
            "python3 scripts/refresh_first_job_dashboard.py",
            "```",
        ]
    )
    SUMMARY_PATH.write_text("\n".join(summary) + "\n", encoding="utf-8")


def publish_docs() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    dashboard_src = OUTPUT_DIR / "dashboard.html"
    if not dashboard_src.exists():
        raise FileNotFoundError(f"Dashboard not found at {dashboard_src}")

    # Publish a stable GitHub Pages entrypoint.
    dashboard_html = dashboard_src.read_text(encoding="utf-8")
    (DOCS_DIR / "index.html").write_text(dashboard_html, encoding="utf-8")
    (DOCS_DIR / "dashboard.html").write_text(dashboard_html, encoding="utf-8")
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    publish_note = "\n".join(
        [
            "# Dashboard Publish Artifacts",
            "",
            "This folder is safe to publish to GitHub Pages.",
            "",
            "- `index.html` is the dashboard entrypoint.",
            "- Raw inputs from `codex_data/` are intentionally excluded.",
            "- Regenerated by `python3 scripts/refresh_first_job_dashboard.py`.",
            "",
        ]
    )
    (DOCS_DIR / "README.md").write_text(publish_note, encoding="utf-8")


def main() -> None:
    input_path = detect_input_file()
    if input_path.suffix.lower() != ".csv":
        raise ValueError(
            f"Detected input file '{input_path.name}' is a Parquet file. "
            "This refresh pipeline currently supports CSV only in this environment. "
            "Provide a CSV refresh file or extend the environment with a Parquet reader."
        )

    validation = validate_csv(input_path)

    fjg.INPUT_CSV = str(input_path)
    fjg.OUT_DIR = str(OUTPUT_DIR)
    fjg.OUT_CSV = str(OUTPUT_DIR / "first_job_after_phd_classified_v2.csv")
    fjg.SED_BROAD_XLSX = str(OUTPUT_DIR / "nsf25349-tab001-002.xlsx")
    fjg.main()

    write_metadata(input_path, validation)
    publish_docs()

    print(f"Refreshed dashboard from {input_path.name}")
    print(
        f"Rows: {validation['row_count']} | Years: {validation['min_grad_year']}–{validation['max_grad_year']}"
    )
    print(f"Dashboard: {OUTPUT_DIR / 'dashboard.html'}")
    print(f"Publish docs: {DOCS_DIR / 'index.html'}")
    print(f"Metadata: {METADATA_PATH}")


if __name__ == "__main__":
    main()
