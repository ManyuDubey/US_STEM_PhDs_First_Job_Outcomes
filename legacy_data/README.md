# Legacy Data Archive

This folder contains the older `first_job_after_phd_classified` dataset files.

Archived files:

- `first_job_after_phd_classified.parquet`
- `first_job_after_phd_classified.csv`
- `first_job_after_phd_classified_schema.json`
- `first_job_after_phd_classified_preview.csv`

These files are retained for audit, comparison, and historical debugging only. They are not used by the current dashboard workflow.

Current workflow:

```bash
python3 scripts/refresh_post_phd_dashboard.py
```

The active workflow builds from:

- `codex_data/post_phd_job_history_mapped.csv`
- `codex_data/post_phd_first_job_dashboard_input.csv`

