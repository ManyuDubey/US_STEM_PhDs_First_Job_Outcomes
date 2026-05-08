# First Job After PhD Classified Dataset

This README summarizes how the `first_job_after_phd_classified` dataset was created, what sources were used, and what known leakage/data-quality issues to keep in mind when using it in Codex or downstream analysis.

## Main files

Recommended local files:

- `first_job_after_phd_classified.parquet` — main dataset for Python/Codex work
- `first_job_after_phd_classified.csv` — CSV backup
- `first_job_after_phd_classified_schema.json` — column names, dtypes, and shape
- `first_job_after_phd_classified_preview.csv` — small preview sample

## Dataset purpose

Each row is intended to represent one matched PhD individual and their first observed Revelio job after PhD graduation. The goal is to classify the organization of that first job into buckets such as university, hospital, government lab, government/public sector, listed company, VC-backed startup, business unclassified, and other unclassified.

## Upstream dataset construction

The upstream first-job table is:

```sql
`fluted-mercury-407006.pq_rev_int.first_job_after_phd`
```

It was created by combining two accepted match sources:

```sql
`fluted-mercury-407006.pq_rev_int.final_accepted_matches`
`fluted-mercury-407006.pq_rev_int.final_accepted_matches_dhrev_enhanced`
```

These were unioned into a single match table using:

- `pq_row_id`
- `goid`
- `author`
- `rev_user_id`
- `grad_year`

Then matched Revelio users were joined to:

```sql
`fluted-mercury-407006.revelio.revelio_individual_position`
```

The first job was defined as the earliest Revelio position where:

- `startdate` is non-null and parseable
- `startdate >= January 1 of grad_year`

For each `pq_row_id`, the earliest qualifying job was selected.

## ProQuest field augmentation

The classified dataset was augmented by joining the first-job table back to:

```sql
`fluted-mercury-407006.proquest.pq_us_stem`
```

using:

- `goid`
- `author`

Added fields include:

- `proquest_year`
- `nsf_primary`
- `nsf_major`
- `nsf_broad`

## Organization classification sources

### 1. Revelio company reference

The first-job rows were joined to:

```sql
`fluted-mercury-407006.revelio.revelio_academic_company_ref`
```

using `rcid`.

This table provides company metadata such as:

- `company`
- `primary_name`
- `ultimate_parent_rcid`
- `ultimate_parent_rcid_name`
- `ticker`
- `exchange_name`
- `cusip`
- `isin`
- `cik`
- `gvkey`
- `naics_code`
- `year_founded`

### 2. Compustat public company data

The classifier uses the uploaded Compustat table:

```sql
`fluted-mercury-407006.COMPUSTAT.us_cusip`
```

It is joined using identifiers such as:

- `gvkey`
- `cusip`
- `cik`
- `ticker`

It is also joined by normalized company name as a fallback.

The key Compustat variable is:

- `ipo_year`

This allows distinguishing whether the person joined before or after the company was publicly listed.

Classification rules:

- If `compustat_ipo_year <= first_job_year`, classify as `Listed Company`.
- If public identifiers exist but IPO date is missing, classify as `Listed Company - IPO Date Missing`.

### 3. PitchBook startup data

Startup identification uses the bridge table:

```sql
`fluted-mercury-407006.pitchbk.pbk_vcna_startup_rev_match_apr2026`
```

This maps:

- Revelio `rcid`
- PitchBook `companyid`

The bridge is then joined to:

```sql
`fluted-mercury-407006.pitchbk.pbk_wrds_comp_vcna`
`fluted-mercury-407006.pitchbk.pbk_wrds_deal_vcna`
```

A company is treated as `Startup / VC-backed Private Firm` if:

- it has VC activity before or during the first-job year
- `first_vc_year <= first_job_year`
- it was not public by the first-job year based on Compustat IPO year
- it does not look like a very large weak-VC-signal firm

The large weak-signal exclusion used was:

```sql
IFNULL(pitchbook_employees, 0) > 5000
AND IFNULL(pitchbook_totalraised, 0) < 20
AND IFNULL(n_vc_rounds, 0) < 3
```

### 4. Name-based classification

Institutional categories are classified using regex over combined text from:

- `company_cleaned`
- `company_raw`
- Revelio company name
- Revelio primary name
- Revelio ultimate parent name

This allows classification even when `rcid` is missing.

## Final organization buckets

The main classification column is:

```text
first_job_org_type
```

Current buckets:

- `University / Academic Institution`
- `Hospital / Health System`
- `Government Lab`
- `Government Agency / Public Sector`
- `Listed Company`
- `Listed Company - IPO Date Missing`
- `Startup / VC-backed Private Firm`
- `Business (Unclassified)`
- `Other / Unclassified`

## Business unclassified bucket

A separate `Business (Unclassified)` bucket was added for rows that are not identified as public, startup, university, hospital, or government, but whose organization names suggest a business entity.

Keywords include:

- `llc`
- `llp`
- `inc`
- `incorporated`
- `corp`
- `corporation`
- `ltd`
- `limited`
- `plc`
- `gmbh`
- `sarl`
- `.com`

The regex uses word boundaries, so `inc` should not match words like `incline`.

## Known leakage / data quality issues

### 1. Missing `rcid` leakage

The main upstream issue was not the Revelio company reference join. The issue was that some first-job position rows had missing `rcid`.

Earlier diagnostics showed:

- Total upstream first-job rows: `312,627`
- Rows with non-null `rcid`: `288,153`
- Rows missing `rcid`: `24,474`
- Rows successfully joined to Revelio company reference: `288,124`

This means almost every non-null `rcid` joined successfully. The leakage was mostly from positions where Revelio did not provide an `rcid`.

To reduce this leakage, the final classifier uses `company_cleaned` and `company_raw` as fallback classification text when `rcid` is missing.

### 2. PitchBook join does not always imply startup

A row can have:

```text
pitchbook_join_source = pitchbook_rcid_join
```

but still be classified as:

```text
Other / Unclassified
```

This is intentional.

A PitchBook join only means the Revelio `rcid` mapped to a PitchBook company. It becomes `Startup / VC-backed Private Firm` only if the VC timing rule is satisfied:

- `first_vc_year` is not null
- `first_vc_year <= first_job_year`
- company was not public by first-job year
- large weak-signal company filter is not triggered

### 3. IPO date missing

Some companies have public identifiers but missing IPO dates. These are separated into:

```text
Listed Company - IPO Date Missing
```

This avoids incorrectly deciding whether the person joined pre-IPO or post-IPO.

### 4. Name fallback classifications are lower confidence

Rows classified using company names rather than `rcid` should be treated as lower confidence.

Useful source columns to check:

- `base_company_source`
- `compustat_join_source`
- `pitchbook_join_source`
- `classification_source`

## Useful columns for analysis

Core identity columns:

- `pq_row_id`
- `goid`
- `author`
- `rev_user_id`
- `grad_year`
- `proquest_year`

First-job columns:

- `first_job_startdate`
- `first_job_enddate`
- `first_job_year`
- `company_cleaned`
- `company_raw`
- `country`
- `rcid`
- `title_raw`
- `title_translated`
- `mapped_role_v3`
- `onet_title`

Field columns:

- `nsf_primary`
- `nsf_major`
- `nsf_broad`

Classification columns:

- `first_job_org_type`
- `classification_source`
- `base_company_source`
- `compustat_join_source`
- `pitchbook_join_source`

Startup/public company columns:

- `pitchbook_companyid`
- `pitchbook_companyname`
- `first_vc_year`
- `pitchbook_yearfounded`
- `pitchbook_employees`
- `pitchbook_totalraised`
- `n_deals_total`
- `n_vc_rounds`
- `compustat_ipo_year`
- `compustat_company_name`

## Recommended caution

Higher-confidence categories:

- `Listed Company` with `classification_source` containing `compustat_ipo_before_or_at_first_job`
- `Startup / VC-backed Private Firm` with `pitchbook_rcid_join`
- Institutional classifications with `base_company_source = revelio_rcid`

Lower-confidence categories:

- classifications with `company_cleaned_fallback`
- `Listed Company - IPO Date Missing`
- `Business (Unclassified)`
- `Other / Unclassified`

## Suggested Codex workflow

When using this dataset in Codex, start with:

1. Load the Parquet file.
2. Inspect `df.shape` and `df.columns`.
3. Check `first_job_org_type` counts.
4. Cross-tab `first_job_org_type` by `classification_source`.
5. Treat fallback classifications separately in robustness checks.

## Current local analysis and dashboard setup

This folder now contains a repeatable local pipeline for refreshing first-job visualizations and a publishable GitHub Pages dashboard.

Key local files:

- `scripts/first_job_graphs.py` — main classification refresh and dashboard generator
- `scripts/refresh_first_job_dashboard.py` — one-command refresh entrypoint
- `config/first_job_overrides.json` — persistent override layer for name standardization and classification fixes
- `outputs/first_job_graphs/dashboard.html` — latest local interactive dashboard
- `docs/index.html` — GitHub Pages publish target
- `outputs/first_job_graphs/refresh_metadata.json` — machine-readable metadata for the last refresh
- `outputs/first_job_graphs/refresh_metadata.md` — human-readable metadata for the last refresh

### One-command refresh workflow

The current refresh workflow is:

```bash
python3 scripts/refresh_first_job_dashboard.py
```

What this does:

- validates the current first-job CSV input
- reruns the `v2` classification logic
- rebuilds static SVG outputs
- rebuilds the interactive dashboard
- refreshes top-organization tables
- writes refresh metadata
- writes publishable GitHub Pages files into `docs/`

### Current input assumptions

The refresh wrapper currently expects a CSV input file, not Parquet, in the local environment.

Preferred input file:

- `codex_data/first_job_after_phd_classified.csv`

The wrapper can auto-detect newer matching CSV files in `codex_data/` if the canonical name is absent, but the canonical CSV filename is the safest workflow.

### Persistent override layer

Durable corrections now live in:

- `config/first_job_overrides.json`

This file is loaded on every refresh and is intended to accumulate improvements over time across backend data versions.

Current supported override types:

- `org_name_overrides` — standardize organization display names
- `classification_exact_overrides` — force an org type for exact organization names
- `classification_regex_overrides` — force an org type based on regex patterns

This means future dataset refreshes do not start from scratch; they inherit the persistent standardization and classification fixes recorded in the config file.

### Dashboard scope

The dashboard currently includes:

- overall sector trends over graduation years
- overall graduate counts by NSF broad field
- matched-file versus SED comparison for NSF broad fields
- interactive field-level trends for `nsf_broad`
- interactive field-level trends for `nsf_major`
- top 10 organizations for selected broad and major fields

The dashboard has:

- hover tooltips
- dropdown selectors
- global start-year and end-year sliders

### Dashboard publishing

The dashboard is currently set up for GitHub Pages publishing from `docs/`.

Current public URL:

- `https://manyudubey.github.io/US_STEM_PhDs_First_Job_Outcomes/`

The refresh script automatically updates:

- `docs/index.html`
- `docs/dashboard.html`
- `docs/.nojekyll`

### Git hygiene

Raw data must not be pushed to GitHub.

This is enforced locally through:

- `.gitignore`

Current ignored local data path:

- `codex_data/`

The intended Git workflow after a dashboard refresh is:

```bash
python3 scripts/refresh_first_job_dashboard.py
git add docs scripts config .gitignore
git commit -m "Refresh dashboard"
git push
```

Do not use `git add .` unless you have explicitly checked what is being staged.

### SED comparison status

Official SED broad-field comparison data currently come from:

- `outputs/first_job_graphs/nsf25349-tab001-002.xlsx`

The dashboard currently restricts the matched-file versus SED comparison to:

- `2014–2020`

There is also a saved NCSES builder selection file in:

- `codex_data/ncses_cust_table_SED_2026-05-07T21_24_18Z.json`

Important:

- that JSON is a table-definition / selection file
- it is not the actual numeric SED table export
- it confirms the builder uses the relevant trend broad and trend major field structures, but by itself it does not extend the numeric SED series

### What a future Codex session should know

If a future Codex session is asked to get up to date in this directory, it should read this README first, then inspect:

1. `outputs/first_job_graphs/refresh_metadata.md`
2. `config/first_job_overrides.json`
3. `scripts/refresh_first_job_dashboard.py`
4. `scripts/first_job_graphs.py`

If a new backend dataset has been dropped into `codex_data/`, the first operational step should usually be:

```bash
python3 scripts/refresh_first_job_dashboard.py
```
