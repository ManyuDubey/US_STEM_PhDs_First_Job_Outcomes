#!/usr/bin/env python3
"""Refresh the first-job dashboard from the current post-PhD input file."""

from __future__ import annotations

import csv
import json
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

CURRENT_INPUT_CSV = CODEX_DATA / "post_phd_first_job_dashboard_input.csv"
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
    if CURRENT_INPUT_CSV.exists():
        return CURRENT_INPUT_CSV

    raise FileNotFoundError(
        f"Current first-job input not found: {CURRENT_INPUT_CSV}. "
        "Run `python3 scripts/build_post_phd_first_job_input.py` or the full "
        "`python3 scripts/refresh_post_phd_dashboard.py` workflow first."
    )


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


def write_metadata(
    input_path: Path,
    validation: Dict[str, object],
    refresh_command: str = "python3 scripts/refresh_first_job_dashboard.py",
) -> None:
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
        "refresh_command": refresh_command,
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
            refresh_command,
            "```",
        ]
    )
    SUMMARY_PATH.write_text("\n".join(summary) + "\n", encoding="utf-8")


def write_landing_page() -> None:
    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PhD Outcomes Dashboard</title>
  <style>
    :root {
      --bg: #f6f3ee;
      --panel: #fffdf8;
      --ink: #222;
      --muted: #68635b;
      --border: #d8d2c4;
      --blue: #1f4e79;
      --green: #4f7f68;
      --red: #a33d3f;
      --gold: #b36b21;
    }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background:
        linear-gradient(180deg, rgba(31,78,121,0.08), rgba(31,78,121,0) 260px),
        var(--bg);
      color: var(--ink);
    }
    .wrap {
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 24px 52px;
    }
    nav {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 56px;
      font-size: 14px;
    }
    nav a {
      color: var(--blue);
      text-decoration: none;
      border-bottom: 1px solid transparent;
    }
    nav a:hover { border-color: var(--blue); }
    .intro {
      max-width: 860px;
      margin-bottom: 34px;
    }
    h1 {
      margin: 0 0 10px;
      font-size: clamp(34px, 5vw, 58px);
      line-height: 1.02;
      letter-spacing: 0;
    }
    .sub {
      margin: 0;
      color: var(--muted);
      font-size: 18px;
      line-height: 1.45;
      max-width: 760px;
    }
    .links {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 18px;
      margin-top: 30px;
    }
    .tile {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      min-height: 210px;
      color: inherit;
      text-decoration: none;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      box-shadow: 0 1px 0 rgba(0,0,0,0.03);
    }
    .tile:hover {
      border-color: var(--blue);
      box-shadow: 0 10px 24px rgba(31,78,121,0.10);
    }
    .kicker {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 12px;
    }
    .tile h2 {
      margin: 0 0 10px;
      font-size: 24px;
      line-height: 1.15;
      letter-spacing: 0;
    }
    .tile p {
      margin: 0;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.42;
    }
    .bar {
      height: 4px;
      width: 80px;
      margin-top: 24px;
      border-radius: 3px;
      background: var(--blue);
    }
    .tile:nth-child(2) .bar { background: var(--green); }
    .tile:nth-child(3) .bar { background: var(--gold); }
    .tile:nth-child(4) .bar { background: var(--red); }
    @media (max-width: 1100px) {
      .links { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 860px) {
      nav { margin-bottom: 34px; }
      .links { grid-template-columns: 1fr; }
      .tile { min-height: 0; }
    }
  </style>
</head>
<body>
  <main class="wrap">
    <nav>
      <a href="index.html">Home</a>
      <a href="dashboard.html">First jobs</a>
      <a href="ncses_comparison.html">NCSES comparison</a>
      <a href="bachelors_countries.html">Bachelor countries</a>
      <a href="first_job_countries_non_us_bachelors.html">International Migration of Non-US PhDs</a>
    </nav>
    <section class="intro">
      <h1>PhD Outcomes Dashboard</h1>
      <p class="sub">A compact portal for first jobs, NCSES coverage, bachelor-country origins, and international migration among non-US bachelor-origin PhDs.</p>
    </section>
    <section class="links" aria-label="Dashboard pages">
      <a class="tile" href="dashboard.html">
        <div>
          <div class="kicker">Career outcomes</div>
          <h2>First Jobs After PhD</h2>
          <p>Sector trends by graduation year, NSF field, major field, and top hiring organizations.</p>
        </div>
        <div class="bar"></div>
      </a>
      <a class="tile" href="ncses_comparison.html">
        <div>
          <div class="kicker">Coverage check</div>
          <h2>NCSES Comparison</h2>
          <p>University-field-year doctorate counts from NCSES compared with the matched Carnegie/NSF data.</p>
        </div>
        <div class="bar"></div>
      </a>
      <a class="tile" href="bachelors_countries.html">
        <div>
          <div class="kicker">Origins</div>
          <h2>Bachelor Countries</h2>
          <p>Top bachelor-degree countries overall and by broad field, major field, primary field, and PhD university.</p>
        </div>
        <div class="bar"></div>
      </a>
      <a class="tile" href="first_job_countries_non_us_bachelors.html">
        <div>
          <div class="kicker">Destinations</div>
          <h2>International Migration of Non-US PhDs</h2>
          <p>Destination countries immediately after the PhD, 3 years later, and 5 years later for non-U.S. bachelor-origin PhDs.</p>
        </div>
        <div class="bar"></div>
      </a>
    </section>
  </main>
</body>
</html>
"""
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")


def publish_docs() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    dashboard_src = OUTPUT_DIR / "dashboard.html"
    if not dashboard_src.exists():
        raise FileNotFoundError(f"Dashboard not found at {dashboard_src}")

    dashboard_html = dashboard_src.read_text(encoding="utf-8")
    (DOCS_DIR / "dashboard.html").write_text(dashboard_html, encoding="utf-8")
    write_landing_page()
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    publish_note = "\n".join(
        [
            "# Dashboard Publish Artifacts",
            "",
            "This folder is safe to publish to GitHub Pages.",
            "",
            "- `index.html` is the landing page.",
            "- `dashboard.html` is the same first-job dashboard under an explicit name.",
            "- `ncses_comparison.html` compares NCSES university-field-year counts with the matched data.",
            "- `bachelors_countries.html` summarizes bachelor-degree countries by field and university.",
            "- `first_job_countries_non_us_bachelors.html` summarizes job destination countries immediately after the PhD, 3 years later, and 5 years later for non-U.S. bachelor-origin PhDs.",
            "- Raw inputs from `codex_data/` are intentionally excluded.",
            "- Regenerated by `python3 scripts/refresh_post_phd_dashboard.py` for the current post-PhD dataset.",
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
