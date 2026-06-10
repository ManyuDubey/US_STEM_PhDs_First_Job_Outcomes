# First Job After PhD Classified Dataset

This README summarizes how the legacy `first_job_after_phd_classified` dataset was created, what sources were used, and what known leakage/data-quality issues to keep in mind when using it in Codex or downstream analysis.

The active dashboard workflow no longer reads these legacy files. Use `python3 scripts/refresh_post_phd_dashboard.py`, which builds from `codex_data/post_phd_job_history_mapped.csv` through `codex_data/post_phd_first_job_dashboard_input.csv`.

## Legacy files

Archived local files are stored in `legacy_data/`:

- `legacy_data/first_job_after_phd_classified.parquet` — archived main dataset
- `legacy_data/first_job_after_phd_classified.csv` — archived CSV backup
- `legacy_data/first_job_after_phd_classified_schema.json` — archived column names, dtypes, and shape
- `legacy_data/first_job_after_phd_classified_preview.csv` — archived small preview sample

Keep these for audit and comparison only. They are not inputs to the current GitHub Pages dashboard refresh.

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

Status as of May 30, 2026: this folder contains a repeatable local pipeline for the current post-PhD job-history dataset and a publishable GitHub Pages dashboard with three pages.

Published pages:

- `docs/index.html` — landing page
- `docs/dashboard.html` — First Jobs After PhD
- `docs/ncses_comparison.html` — NCSES / ProQuest / matched-ProQuest coverage
- `docs/bachelors_countries.html` — bachelor-degree country origins
- `docs/first_job_countries_non_us_bachelors.html` — International Migration of Non-US PhDs, covering destination countries immediately after the PhD, 3 years later, and 5 years later for non-U.S. bachelor-origin PhDs

Current public URL:

- `https://manyudubey.github.io/US_STEM_PhDs_First_Job_Outcomes/`

### Current refresh workflow

Use the post-PhD refresh entrypoint:

```bash
python3 scripts/refresh_post_phd_dashboard.py
```

This runs, in order:

- `scripts/build_post_phd_first_job_input.py`
- `scripts/refresh_first_job_dashboard.py`
- `scripts/build_ncses_comparison_page.py`
- `scripts/build_bachelors_country_page.py`
- `scripts/build_first_job_country_page.py`

The older `python3 scripts/refresh_first_job_dashboard.py` still refreshes the first-job page, but it does not rebuild the NCSES or bachelor-country pages. Use `refresh_post_phd_dashboard.py` when preparing the site for GitHub Pages.

### Current raw inputs

The current dashboard build depends on these local raw inputs:

- `codex_data/post_phd_job_history_mapped.csv`
- `codex_data/goid_user_id_nsf.csv`
- `deg_info.csv`
- `pq.csv`
- `ncses_table_srv_data_SED_2026-05-26T19_44_34Z.zip`

Raw inputs are local working files and should not be pushed unless there is an explicit decision to version them. At the moment, `deg_info.csv`, `pq.csv`, and the NCSES zip are untracked local files.

### First Jobs After PhD page

The first-job page is generated from `codex_data/post_phd_job_history_mapped.csv` via `codex_data/post_phd_first_job_dashboard_input.csv`.

Current operational rule:

- `job_order == 1` is treated as the first post-PhD job sequence marker for each `rev_user_id`.

Important nuance:

- `job_order` is not always unique per user.
- If a one-row-per-user extract is needed, use `job_order == 1` and then break ties deterministically, for example by earliest `job_start_year`, lowest `position_number`, or lowest `position_id`.
- Some later-ordered rows can have earlier `job_start_year`; these appear to be pre-PhD cases, overlapping jobs, or timing noise and should not overturn `job_order == 1`.

The First Jobs page is capped at graduation years `1980-2019`.

The removed SED comparison is no longer shown on the First Jobs page.

### First-job classification rules

The current first-job classifier uses:

- Carnegie `cchie` categories from `goid_user_id_nsf.csv` for universities, R1/R2 universities, medical schools, and research institutions.
- DISCERN public-firm signals for publicly listed firms.
- PitchBook-backed timing signals for startup-backed firms.
- A lightweight non-US listed-company classification.
- Fallback regex and NAICS/name rules for government labs, public sector, hospitals, universities, research nonprofits, self-employment, business-like residuals, and other residuals.

Important unresolved issue:

- Some public-company classification is not fully date-aware yet. For example, Google / Alphabet can still be treated as a public firm before the IPO in the current first-job output. This is known and should be fixed later with date-aware public/startup logic.

### First-job graph fields

The First Jobs page excludes the same non-STEM/social-science block used elsewhere:

- `business`
- `education`
- `humanities and arts`
- `other non science and engineering`
- `psychology`
- `social sciences`

Current included broad fields are:

- `Agricultural sciences and natural resources`
- `Biological and biomedical sciences`
- `Computer and information sciences`
- `Engineering`
- `Geosciences, atmospheric, and ocean sciences`
- `Health sciences`
- `Mathematics and statistics`
- `Multidisciplinary sciences`
- `Physical sciences`

### NCSES / ProQuest comparison page

The NCSES page compares three series by year, institution, and NSF field:

- NCSES official doctorate counts
- ProQuest baseline counts
- matched ProQuest counts from the matched post-PhD data

Current count units:

- NCSES counts are summed from `Doctorate Recipients by Institution` in the NCSES zip.
- ProQuest baseline counts distinct `pq_goid_row` values from `pq.csv`, falling back to `goid` only if `pq_goid_row` is missing.
- Matched ProQuest counts distinct matched `goid` values, falling back to `rev_user_id` only if `goid` is missing.

Current NCSES page scope:

- years `1980-2019`
- same social-science / humanities exclusions as the other pages
- Carnegie institution names are the canonical institution names

Current NCSES totals after filtering:

- NCSES: `872,979`
- ProQuest baseline: `831,904`
- matched ProQuest: `354,992`
- ProQuest / NCSES coverage: `95.3%`
- matched ProQuest / NCSES coverage: `40.7%`
- matched NCSES institutions: `367 / 422`

Field-name handling:

- NCSES uses `Trend Broad Fields` and `Trend Major Fields`.
- ProQuest uses `nsf_broad` and `nsf_major`.
- Matched ProQuest uses NSF fields from `goid_user_id_nsf.csv`.
- Labels are cleaned and normalized before comparison.
- One explicit alias is currently used: `Multidisciplinary/ interdisciplinary sciences` -> `Multidisciplinary sciences`.

Institution-name handling:

- Canonical names come from Carnegie names in `pq.csv` and `goid_user_id_nsf.csv`.
- NCSES institution names are crosswalked to Carnegie names using manual aliases, normalized exact/variant matches, unique prefix matches, and conservative fuzzy matching.
- The crosswalk output is written to `outputs/first_job_graphs/ncses_comparison/ncses_institution_crosswalk.csv`.

Known NCSES comparison caveats:

- Coverage can exceed `100%` for some institution-field-year cells because ProQuest, NCSES, and Carnegie taxonomy boundaries do not always align.
- Some unmatched NCSES institutions remain and need manual alias work.
- `Multidisciplinary sciences` appears in ProQuest/matched data but not as a nonzero NCSES broad-field total in the current NCSES extract, so treat that row as taxonomy mismatch rather than substantive overcoverage.

### Bachelor countries page

The bachelor-country page uses `deg_info.csv` to infer bachelor-degree country origins for matched PhDs.

Current rules:

- Graduation year is `grad_year`.
- PhD university is standardized to `carnegie_name`.
- Social sciences, education, psychology, business, humanities/arts, and other non-science fields are excluded.
- United States is omitted from the plotted country series so non-US sending countries are visible.
- The denominator still includes all PhDs in the selected university, field, and graduation year with an identified bachelor country, including U.S. bachelor degrees.
- Graphs are capped at `2019`.

Bachelor-row inference currently recognizes:

- explicit Revelio bachelor rows
- bachelor-like degree strings
- safe bachelor abbreviations
- safe medical bachelor equivalents such as `MBBS`
- safe engineering bachelor equivalents
- selected typo/word variants

Current bachelor-country summary:

- total matched users: `387,625`
- included STEM/non-social-science users: `384,385`
- display users through 2019 after exclusions: `355,365`
- users with bachelor country through 2019 after exclusions: `274,794`
- display bachelor-country coverage: `77.3%`

### Job countries for non-U.S. bachelor origins

The job-country destination page joins `codex_data/post_phd_first_job_dashboard_input.csv`, `codex_data/post_phd_job_history_mapped.csv`, and `outputs/first_job_graphs/bachelors_countries/bachelor_country_by_user.csv`.

Current rules:

- The sample is restricted to matched PhD recipients with an identified bachelor country outside the United States.
- The immediate outcome is the `country` field on the first observed post-PhD job.
- The 3-year and 5-year outcomes select the active job at `grad_year + 3` and `grad_year + 5`, preferring the latest active start if jobs overlap.
- Destination displays keep the top 7 countries for each group, including the United States.
- United States is suppressed in the plotted country lines so smaller destination countries are readable, but it remains visible in the click details and summary tables.
- Shares use users with a known country at the selected timing as the denominator; missing country is reported in the summary but not plotted.
- Graph views include overall, U.S. versus non-U.S., NSF broad field, NSF major field, bachelor country, and PhD university.
- Graphs are capped at `2019`.

Current outputs:

- `docs/first_job_countries_non_us_bachelors.html`
- `outputs/first_job_graphs/first_job_countries_non_us_bachelors/first_job_country_by_non_us_bachelor_user.csv`
- `outputs/first_job_graphs/first_job_countries_non_us_bachelors/first_job_country_time_series.csv`
- `outputs/first_job_graphs/first_job_countries_non_us_bachelors/summary.json`

### Git hygiene

Raw data should not be pushed to GitHub unless explicitly intended.

Before committing, inspect:

```bash
git status
```

Typical site/code commit:

```bash
git add docs/dashboard.html docs/ncses_comparison.html docs/bachelors_countries.html docs/first_job_countries_non_us_bachelors.html docs/index.html scripts/build_ncses_comparison_page.py scripts/build_bachelors_country_page.py scripts/build_first_job_country_page.py scripts/first_job_graphs.py scripts/refresh_post_phd_dashboard.py scripts/build_post_phd_first_job_input.py
git commit -m "Refresh PhD dashboard pages"
git push
```

Do not use `git add .` unless you have explicitly checked what is being staged.

### What a future Codex session should know

If a future Codex session is asked to get up to date in this directory, it should read this README first, then inspect:

1. `docs/README.md`
2. `outputs/first_job_graphs/post_phd_first_job_dashboard_input_audit.md`
3. `outputs/first_job_graphs/ncses_comparison/summary.json`
4. `outputs/first_job_graphs/bachelors_countries/summary.json`
5. `scripts/refresh_post_phd_dashboard.py`
6. `scripts/build_post_phd_first_job_input.py`
7. `scripts/first_job_graphs.py`
8. `scripts/build_ncses_comparison_page.py`
9. `scripts/build_bachelors_country_page.py`
10. `scripts/build_first_job_country_page.py`

If a new backend dataset has been dropped into `codex_data/`, the first operational step should usually be:

```bash
python3 scripts/refresh_post_phd_dashboard.py
```

If the task involves the public dashboard, also remember:

- `docs/index.html` is the GitHub Pages entrypoint.
- The public site is `https://manyudubey.github.io/US_STEM_PhDs_First_Job_Outcomes/`.
- Raw files in `codex_data/` and large root CSV/ZIP inputs must not be pushed without an explicit decision.
