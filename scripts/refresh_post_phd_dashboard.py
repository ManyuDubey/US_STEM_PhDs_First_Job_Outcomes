#!/usr/bin/env python3
"""Refresh the dashboard from the mapped post-PhD job-history dataset."""

from __future__ import annotations

from pathlib import Path

import build_post_phd_first_job_input as builder
import build_bachelors_country_page as bachelors
import build_ncses_comparison_page as ncses
import first_job_graphs as fjg
import refresh_first_job_dashboard as refresh


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "first_job_graphs"
DOCS_DIR = ROOT / "docs"


def main() -> None:
    nsf = builder.load_nsf_crosswalk()
    rows, diagnostics = builder.read_first_job_rows(nsf)
    builder.write_rows(rows)
    builder.write_audit(nsf, diagnostics)

    input_path = builder.OUT_CSV
    validation = refresh.validate_csv(input_path)

    fjg.INPUT_CSV = str(input_path)
    fjg.OUT_DIR = str(OUTPUT_DIR)
    fjg.OUT_CSV = str(OUTPUT_DIR / "first_job_after_phd_classified_v2.csv")
    fjg.SED_BROAD_XLSX = str(OUTPUT_DIR / "nsf25349-tab001-002.xlsx")
    fjg.main()

    refresh.write_metadata(
        input_path,
        validation,
        refresh_command="python3 scripts/refresh_post_phd_dashboard.py",
    )
    refresh.publish_docs()
    ncses.main()
    bachelors.main()

    print(f"Built first-job input from {builder.MAPPED_CSV.name}")
    print(f"Rows: {validation['row_count']} | Years: {validation['min_grad_year']}-{validation['max_grad_year']}")
    print(f"Dashboard: {OUTPUT_DIR / 'dashboard.html'}")
    print(f"Publish docs: {DOCS_DIR / 'index.html'}")
    print(f"Input audit: {builder.AUDIT_MD}")


if __name__ == "__main__":
    main()
