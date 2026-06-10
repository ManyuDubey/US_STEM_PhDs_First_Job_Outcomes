#!/usr/bin/env python3
"""Build job-country dashboard for non-US bachelor-degree holders."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict

import dashboard_data_common as common


OUT_DIR = common.OUTPUT_DIR / "first_job_countries_non_us_bachelors"
SUMMARY_JSON = OUT_DIR / "summary.json"
USER_CSV = OUT_DIR / "first_job_country_by_non_us_bachelor_user.csv"
AGG_CSV = OUT_DIR / "first_job_country_time_series.csv"
DOC_PATH = common.DOCS_DIR / "first_job_countries_non_us_bachelors.html"
BACHELOR_USER_CSV = common.OUTPUT_DIR / "bachelors_countries" / "bachelor_country_by_user.csv"

MAX_DASHBOARD_YEAR = 2019
TOP_COUNTRY_LIMIT = 7
MIN_BROAD_GROUP = 25
MIN_MAJOR_GROUP = 40
MIN_BACHELOR_COUNTRY_GROUP = 40
MIN_PHD_UNIVERSITY_GROUP = 40
US_COUNTRY = "United States"
HORIZONS = [
    ("first_job", "Immediately after PhD", 0),
    ("year_3", "3 years after PhD", 3),
    ("year_5", "5 years after PhD", 5),
]

COLORS = [
    "#1f4e79",
    "#c43c39",
    "#5b8e7d",
    "#d97b29",
    "#6f5aa7",
    "#7a8f3b",
    "#a23b72",
    "#4f6d7a",
    "#8c7a5b",
    "#2f7f7f",
    "#777777",
]


def horizon_country_group(country: str, horizon_label: str) -> str:
    if country == US_COUNTRY:
        return "United States"
    if country:
        return f"Non-US destination ({horizon_label})"
    return f"Missing destination ({horizon_label})"


def sort_value(value: object, default: int) -> int:
    parsed = common.to_int(value)
    return parsed if parsed is not None else default


def job_score(row: Dict[str, str]) -> tuple[int, str, int, int, int]:
    position_id = sort_value(row.get("position_id"), 999999999)
    return (
        sort_value(row.get("job_start_year"), -1),
        common.clean(row.get("start_dt")),
        -sort_value(row.get("job_order"), 999999),
        -sort_value(row.get("position_number"), 999999),
        -position_id,
    )


def load_first_job_rows() -> dict[str, Dict[str, str]]:
    rows: dict[str, Dict[str, str]] = {}
    with common.FIRST_JOB_INPUT.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_id = common.norm_id(row.get("rev_user_id"))
            if not user_id:
                continue
            country = common.clean(row.get("country"))
            rows[user_id] = {
                "rev_user_id": user_id,
                "goid": common.norm_id(row.get("goid")),
                "grad_year": common.clean(row.get("grad_year")),
                "first_job_startdate": common.clean(row.get("first_job_startdate")),
                "first_job_country": common.normalize_country(country) if country else "",
                "first_job_org_type": common.clean(row.get("first_job_org_type")),
                "company_cleaned": common.clean(row.get("company_cleaned")),
                "company_raw": common.clean(row.get("company_raw")),
            }
    return rows


def add_point_in_time_countries(rows: list[Dict[str, str]], diagnostics: Counter) -> None:
    users = {row["rev_user_id"]: row for row in rows}
    targets: dict[str, dict[str, int]] = {}
    for row in rows:
        grad_year = common.to_int(row.get("grad_year"))
        if grad_year is None:
            continue
        targets[row["rev_user_id"]] = {
            horizon_key: grad_year + offset
            for horizon_key, _label, offset in HORIZONS
            if horizon_key != "first_job"
        }

    best: dict[tuple[str, str], tuple[tuple[int, str, int, int, int], Dict[str, str]]] = {}
    with common.CODEX_DATA.joinpath("post_phd_job_history_mapped.csv").open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for job in reader:
            user_id = common.norm_id(job.get("rev_user_id"))
            if user_id not in targets:
                continue
            start_year = common.to_int(job.get("job_start_year"))
            if start_year is None:
                diagnostics["history_missing_start_year"] += 1
                continue
            end_year = common.to_int(job.get("job_end_year"))
            country = common.clean(job.get("country"))
            if not country:
                diagnostics["history_active_candidate_missing_country"] += 1
                continue
            country = common.normalize_country(country)
            for horizon_key, target_year in targets[user_id].items():
                if start_year > target_year:
                    continue
                if end_year is not None and end_year < target_year:
                    continue
                key = (user_id, horizon_key)
                scored = {
                    "country": country,
                    "start_dt": common.clean(job.get("start_dt")),
                    "end_dt": common.clean(job.get("end_dt")),
                    "job_start_year": common.clean(job.get("job_start_year")),
                    "job_end_year": common.clean(job.get("job_end_year")),
                    "job_order": common.clean(job.get("job_order")),
                    "position_number": common.clean(job.get("position_number")),
                    "position_id": common.clean(job.get("position_id")),
                    "company_cleaned": common.clean(job.get("company_cleaned")),
                    "company_raw": common.clean(job.get("company_raw")),
                }
                score = job_score(scored)
                if key not in best or score > best[key][0]:
                    best[key] = (score, scored)

    for row in rows:
        for horizon_key, horizon_label, _offset in HORIZONS:
            if horizon_key == "first_job":
                row[f"{horizon_key}_country_group"] = horizon_country_group(
                    row.get("first_job_country", ""),
                    horizon_label,
                )
                continue
            selected = best.get((row["rev_user_id"], horizon_key), (None, {}))[1]
            country = selected.get("country", "")
            row[f"{horizon_key}_country"] = country
            row[f"{horizon_key}_country_group"] = horizon_country_group(country, horizon_label)
            row[f"{horizon_key}_start_dt"] = selected.get("start_dt", "")
            row[f"{horizon_key}_end_dt"] = selected.get("end_dt", "")
            row[f"{horizon_key}_job_start_year"] = selected.get("job_start_year", "")
            row[f"{horizon_key}_job_end_year"] = selected.get("job_end_year", "")
            row[f"{horizon_key}_job_order"] = selected.get("job_order", "")
            row[f"{horizon_key}_position_id"] = selected.get("position_id", "")
            row[f"{horizon_key}_company_cleaned"] = selected.get("company_cleaned", "")
            row[f"{horizon_key}_company_raw"] = selected.get("company_raw", "")
            if country:
                diagnostics[f"with_{horizon_key}_country"] += 1
            else:
                diagnostics[f"missing_{horizon_key}_country"] += 1


def load_non_us_bachelor_rows() -> tuple[list[Dict[str, str]], Counter]:
    diagnostics: Counter = Counter()
    if not BACHELOR_USER_CSV.exists():
        raise FileNotFoundError(
            f"Missing bachelor-country user file: {BACHELOR_USER_CSV}. "
            "Run `python3 scripts/build_bachelors_country_page.py` first."
        )

    first_jobs = load_first_job_rows()
    rows: list[Dict[str, str]] = []
    with BACHELOR_USER_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for bachelor in reader:
            diagnostics["bachelor_user_rows"] += 1
            user_id = common.norm_id(bachelor.get("rev_user_id"))
            bachelor_country = common.clean(bachelor.get("bachelor_country"))
            if not bachelor_country:
                diagnostics["missing_bachelor_country"] += 1
                continue
            bachelor_country = common.normalize_country(bachelor_country)
            if bachelor_country == US_COUNTRY:
                diagnostics["us_bachelor_country"] += 1
                continue

            first_job = first_jobs.get(user_id)
            if not first_job:
                diagnostics["missing_first_job_row"] += 1
                continue

            grad_year = common.to_int(bachelor.get("grad_year") or first_job.get("grad_year"))
            if grad_year is None:
                diagnostics["missing_grad_year"] += 1
                continue

            first_job_country = first_job.get("first_job_country", "")
            if first_job_country:
                diagnostics["with_first_job_country"] += 1
            else:
                diagnostics["missing_first_job_country"] += 1

            destination_group = horizon_country_group(first_job_country, "Immediately after PhD")

            rows.append(
                {
                    "rev_user_id": user_id,
                    "goid": common.norm_id(bachelor.get("goid")) or first_job.get("goid", ""),
                    "grad_year": str(grad_year),
                    "nsf_broad": common.clean(bachelor.get("nsf_broad")),
                    "nsf_major": common.clean(bachelor.get("nsf_major")),
                    "nsf_primary": common.clean(bachelor.get("nsf_primary")),
                    "phd_institution": common.clean(bachelor.get("phd_institution")),
                    "phd_institution_norm": common.clean(bachelor.get("phd_institution_norm")),
                    "carnegie_unitid": common.clean(bachelor.get("carnegie_unitid")),
                    "bachelor_country": bachelor_country,
                    "bachelor_university": common.clean(bachelor.get("bachelor_university")),
                    "bachelor_country_source": common.clean(bachelor.get("bachelor_country_source")),
                    "bachelor_degree_signal": common.clean(bachelor.get("bachelor_degree_signal")),
                    "first_job_country": first_job_country,
                    "first_job_country_group": destination_group,
                    "first_job_startdate": first_job.get("first_job_startdate", ""),
                    "first_job_org_type": first_job.get("first_job_org_type", ""),
                    "company_cleaned": first_job.get("company_cleaned", ""),
                    "company_raw": first_job.get("company_raw", ""),
                }
            )
            diagnostics["non_us_bachelor_users"] += 1

    diagnostics["first_job_rows"] = len(first_jobs)
    add_point_in_time_countries(rows, diagnostics)
    return rows, diagnostics


def add_country_counts(
    buckets: dict[str, dict[str, dict[int, Counter]]],
    view: str,
    group: str,
    year: int,
    country: str,
) -> None:
    buckets[view][group][year][country] += 1


def top_countries(by_year_country: dict[int, Counter], limit: int = TOP_COUNTRY_LIMIT) -> list[str]:
    totals: Counter = Counter()
    for counter in by_year_country.values():
        totals.update(counter)
    ordered = [country for country, _count in totals.most_common() if country]
    selected = ordered[:limit]
    if US_COUNTRY in totals and US_COUNTRY not in selected:
        selected = ordered[: max(0, limit - 1)] + [US_COUNTRY]
        selected = [country for country, _count in Counter({c: totals[c] for c in selected}).most_common()]
    return selected[:limit]


def point_breakdowns(by_year_country: dict[int, Counter], limit: int = TOP_COUNTRY_LIMIT) -> list[list[object]]:
    breakdowns: list[list[object]] = []
    for year in sorted(by_year_country):
        counter = by_year_country[year]
        total = sum(counter.values())
        selected = top_countries({year: counter}, limit=limit)
        values = [
            [country, counter.get(country, 0), round(counter.get(country, 0) / total, 6) if total else 0]
            for country in selected
            if counter.get(country, 0)
        ]
        breakdowns.append([year, total, values])
    return breakdowns


def series_for_group(by_year_country: dict[int, Counter], top: list[str]) -> list[Dict[str, object]]:
    years = sorted(by_year_country)
    countries = list(top)

    series: list[Dict[str, object]] = []
    for idx, country in enumerate(countries):
        values = []
        for year in years:
            counter = by_year_country[year]
            denom = sum(counter.values())
            count = counter.get(country, 0)
            values.append(
                {
                    "year": year,
                    "count": count,
                    "total": denom,
                    "share": round(count / denom, 6) if denom else 0,
                }
            )
        if any(value["count"] for value in values):
            series.append(
                {
                    "name": country,
                    "label": country,
                    "color": COLORS[idx % len(COLORS)],
                    "values": values,
                }
            )
    return series


def build_dashboard_payload(rows: list[Dict[str, str]], diagnostics: Counter) -> tuple[dict[str, object], list[Dict[str, object]]]:
    buckets: dict[str, dict[str, dict[str, dict[int, Counter]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    )
    detail_buckets: dict[str, dict[str, dict[str, dict[int, Counter]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    )
    group_thresholds = {
        "overall": 1,
        "us_split": 1,
        "broad": MIN_BROAD_GROUP,
        "major": MIN_MAJOR_GROUP,
        "bachelor_country": MIN_BACHELOR_COUNTRY_GROUP,
        "phd_university": MIN_PHD_UNIVERSITY_GROUP,
    }
    display_stats: Counter = Counter()
    aggregate_rows: list[Dict[str, object]] = []

    for row in rows:
        year = common.to_int(row.get("grad_year"))
        if year is None or year > MAX_DASHBOARD_YEAR:
            continue
        display_stats["display_non_us_bachelor_users"] += 1

        for horizon_key, horizon_label, _offset in HORIZONS:
            country = row.get(f"{horizon_key}_country", "")
            if not country:
                display_stats[f"display_missing_{horizon_key}_country"] += 1
                continue
            display_stats[f"display_with_{horizon_key}_country"] += 1

            add_country_counts(buckets[horizon_key], "overall", "All non-US bachelor origins", year, country)
            add_country_counts(detail_buckets[horizon_key], "overall", "All non-US bachelor origins", year, country)
            add_country_counts(
                buckets[horizon_key],
                "us_split",
                "U.S. versus non-U.S. destination",
                year,
                row.get(f"{horizon_key}_country_group", horizon_country_group(country, horizon_label)),
            )
            add_country_counts(
                detail_buckets[horizon_key],
                "us_split",
                "U.S. versus non-U.S. destination",
                year,
                country,
            )
            if row.get("nsf_broad"):
                add_country_counts(buckets[horizon_key], "broad", row["nsf_broad"], year, country)
                add_country_counts(detail_buckets[horizon_key], "broad", row["nsf_broad"], year, country)
            if row.get("nsf_major"):
                add_country_counts(buckets[horizon_key], "major", row["nsf_major"], year, country)
                add_country_counts(detail_buckets[horizon_key], "major", row["nsf_major"], year, country)
            if row.get("bachelor_country"):
                add_country_counts(buckets[horizon_key], "bachelor_country", row["bachelor_country"], year, country)
                add_country_counts(detail_buckets[horizon_key], "bachelor_country", row["bachelor_country"], year, country)
            if row.get("phd_institution"):
                add_country_counts(buckets[horizon_key], "phd_university", row["phd_institution"], year, country)
                add_country_counts(detail_buckets[horizon_key], "phd_university", row["phd_institution"], year, country)

    horizon_views: dict[str, dict[str, list[dict[str, object]]]] = {}
    for horizon_key, _horizon_label, _offset in HORIZONS:
        views: dict[str, list[dict[str, object]]] = {}
        for view, groups in buckets[horizon_key].items():
            entries = []
            for group, by_year_country in groups.items():
                total = sum(sum(counter.values()) for counter in by_year_country.values())
                if total < group_thresholds.get(view, 1):
                    continue
                top = ["United States", f"Non-US destination ({dict((k, v) for k, v, _ in HORIZONS)[horizon_key]})"] if view == "us_split" else top_countries(by_year_country)
                series = series_for_group(by_year_country, top)
                entry = {
                    "group": group,
                    "n_with_country": total,
                    "year_min": min(by_year_country),
                    "year_max": max(by_year_country),
                    "series": series,
                    "point_breakdowns": point_breakdowns(
                        detail_buckets[horizon_key][view].get(group, by_year_country)
                    ),
                }
                entries.append(entry)
                for serie in series:
                    for value in serie["values"]:
                        aggregate_rows.append(
                            {
                                "horizon": horizon_key,
                                "view": view,
                                "group": group,
                                "destination": serie["name"],
                                "year": value["year"],
                                "count": value["count"],
                                "total_with_country": value["total"],
                                "share": value["share"],
                            }
                        )
            entries.sort(key=lambda item: (-int(item["n_with_country"]), str(item["group"])))
            if view in {"overall", "us_split"}:
                entries.sort(key=lambda item: str(item["group"]))
            views[view] = entries
        horizon_views[horizon_key] = views

    all_years = sorted(
        {
            int(value["year"])
            for views in horizon_views.values()
            for groups in views.values()
            for group in groups
            for serie in group["series"]
            for value in serie["values"]
        }
    )

    compact_horizons: dict[str, dict[str, list[list[object]]]] = {}
    for horizon_key, views in horizon_views.items():
        compact_views: dict[str, list[list[object]]] = {}
        for view, groups in views.items():
            compact_groups = []
            for group in groups:
                compact_series = []
                for serie in group["series"]:
                    compact_series.append(
                        [
                            serie["name"],
                            serie["label"],
                            serie["color"],
                            [[v["year"], v["count"], v["total"]] for v in serie["values"]],
                        ]
                    )
                compact_groups.append(
                    [
                        group["group"],
                        group["n_with_country"],
                        group["year_min"],
                        group["year_max"],
                        compact_series,
                        group["point_breakdowns"],
                    ]
                )
            compact_views[view] = compact_groups
        compact_horizons[horizon_key] = compact_views

    summary = {
        **dict(diagnostics),
        "max_dashboard_year": MAX_DASHBOARD_YEAR,
        "top_country_limit": TOP_COUNTRY_LIMIT,
        "min_broad_group": MIN_BROAD_GROUP,
        "min_major_group": MIN_MAJOR_GROUP,
        "min_bachelor_country_group": MIN_BACHELOR_COUNTRY_GROUP,
        "min_phd_university_group": MIN_PHD_UNIVERSITY_GROUP,
        "year_min": min(all_years) if all_years else None,
        "year_max": max(all_years) if all_years else None,
        "display_non_us_bachelor_users": display_stats["display_non_us_bachelor_users"],
    }
    for horizon_key, _horizon_label, _offset in HORIZONS:
        with_country = display_stats[f"display_with_{horizon_key}_country"]
        missing_country = display_stats[f"display_missing_{horizon_key}_country"]
        summary[f"display_with_{horizon_key}_country"] = with_country
        summary[f"display_missing_{horizon_key}_country"] = missing_country
        summary[f"display_{horizon_key}_country_coverage"] = round(
            with_country / display_stats["display_non_us_bachelor_users"],
            4,
        ) if display_stats["display_non_us_bachelor_users"] else 0
        summary[f"{horizon_key}_broad_groups"] = len(compact_horizons.get(horizon_key, {}).get("broad", []))
        summary[f"{horizon_key}_major_groups"] = len(compact_horizons.get(horizon_key, {}).get("major", []))
        summary[f"{horizon_key}_bachelor_country_groups"] = len(compact_horizons.get(horizon_key, {}).get("bachelor_country", []))
        summary[f"{horizon_key}_phd_university_groups"] = len(compact_horizons.get(horizon_key, {}).get("phd_university", []))

    payload = {
        "summary": summary,
        "horizons": [
            {"key": key, "label": label, "offset": offset}
            for key, label, offset in HORIZONS
        ],
        "views": compact_horizons,
    }
    return payload, aggregate_rows


def write_page(payload: dict[str, object]) -> None:
    data_json = json.dumps(payload)
    body = """
    <div class="card"><div id="stats" class="stats"></div></div>
    <div class="card">
      <div class="controls">
        <div class="control">
          <label for="horizon-select">Timing</label>
          <select id="horizon-select"></select>
        </div>
        <div class="control">
          <label for="view-select">View</label>
          <select id="view-select">
            <option value="overall">Overall destination countries</option>
            <option value="us_split">U.S. versus non-U.S.</option>
            <option value="broad">NSF broad field</option>
            <option value="major">NSF major field</option>
            <option value="bachelor_country">Bachelor country</option>
            <option value="phd_university">PhD university</option>
          </select>
        </div>
        <div class="control">
          <label for="group-select">Group</label>
          <select id="group-select"></select>
        </div>
        <div class="year-controls">
        <div class="control year-control">
          <label for="year-start">Start year</label>
          <input id="year-start" type="range">
          <span id="year-start-label" class="range-value"></span>
        </div>
        <div class="control year-control">
          <label for="year-end">End year</label>
          <input id="year-end" type="range">
          <span id="year-end-label" class="range-value"></span>
        </div>
        </div>
      </div>
      <div id="chart-title" class="title"></div>
      <div id="chart-subtitle" class="subtitle"></div>
      <div class="chart-box">
        <canvas id="country-chart" class="chart"></canvas>
        <div id="tooltip" class="tooltip"></div>
      </div>
      <div id="point-details" class="note">Click a line to isolate that country. Click a point to see the top 7 destination countries for that group and graduation year, including the United States.</div>
      <div class="note">Sample is restricted to matched PhD recipients with an identified bachelor degree country outside the United States. The immediate measure uses the first observed post-PhD job. The 3-year and 5-year measures select the active job at graduation year plus 3 or 5, preferring the latest active start if jobs overlap. The U.S. is suppressed in the plotted lines so non-U.S. destinations remain readable, but it is retained in click details and tables. Shares use users with a known country at the selected timing as the denominator; missing country is reported in the summary but not plotted. Graduation cohorts are shown through 2019.</div>
    </div>
    <div class="card">
      <h2>Destination Summary</h2>
      <div id="country-table"></div>
    </div>
    """
    script = """
  <script>
    const DATA = __DATA__;
    const views = DATA.views || {};
    const horizons = DATA.horizons || [];
    const fmt = (n) => Number(n || 0).toLocaleString();
    const pct = (x) => (Number(x || 0) * 100).toFixed(1) + '%';
    const horizonSelect = document.getElementById('horizon-select');
    const viewSelect = document.getElementById('view-select');
    const groupSelect = document.getElementById('group-select');
    const startInput = document.getElementById('year-start');
    const endInput = document.getElementById('year-end');
    const startLabel = document.getElementById('year-start-label');
    const endLabel = document.getElementById('year-end-label');
    const tooltip = document.getElementById('tooltip');
    const pointDetails = document.getElementById('point-details');
    const suppressedPlotCountries = new Set(['United States']);
    let hoverPoints = [];
    let hoverSegments = [];
    let selectedSeries = null;

    function unpackGroup(g) {
      if (!g) return null;
      return {
        group: g[0],
        n: g[1],
        year_min: g[2],
        year_max: g[3],
        series: (g[4] || []).map(s => ({
          name: s[0],
          label: s[1],
          color: s[2],
          values: (s[3] || []).map(v => ({
            year: v[0],
            count: v[1],
            total: v[2],
            share: v[2] ? v[1] / v[2] : 0
          }))
        })),
        pointBreakdowns: Object.fromEntries((g[5] || []).map(row => [
          row[0],
          {
            total: row[1],
            countries: (row[2] || []).map(item => ({
              country: item[0],
              count: item[1],
              share: item[2]
            }))
          }
        ]))
      };
    }
    function selectedGroups() {
      const horizon = selectedHorizon();
      return ((views[horizon.key] || {})[viewSelect.value] || []).map(unpackGroup);
    }
    function selectedHorizon() {
      return horizons[Number(horizonSelect.value || 0)] || horizons[0] || {key: 'first_job', label: 'Immediately after PhD'};
    }
    function selectedGroup() {
      return selectedGroups()[Number(groupSelect.value || 0)];
    }
    function setStats() {
      const s = DATA.summary || {};
      const horizon = selectedHorizon();
      document.getElementById('stats').innerHTML = [
        ['Non-U.S. bachelor users', fmt(s.display_non_us_bachelor_users)],
        ['With known country', fmt(s[`display_with_${horizon.key}_country`])],
        ['Country coverage', pct(s[`display_${horizon.key}_country_coverage`])],
        ['Broad fields', fmt(s[`${horizon.key}_broad_groups`])],
        ['Major fields', fmt(s[`${horizon.key}_major_groups`])]
      ].map(([label,value]) => `<div class="stat"><div class="value">${value}</div><div class="label">${label}</div></div>`).join('');
    }
    function fillHorizons() {
      horizonSelect.innerHTML = horizons.map((h, i) => `<option value="${i}">${h.label}</option>`).join('');
    }
    function fillGroups() {
      const groups = selectedGroups();
      groupSelect.innerHTML = groups.map((g, i) => `<option value="${i}">${g.group}</option>`).join('');
      if (!groups.length) groupSelect.innerHTML = '<option value="0">No data</option>';
      updateYearBounds();
    }
    function updateYearBounds() {
      const group = selectedGroup();
      const minYear = group ? group.year_min : DATA.summary.year_min;
      const maxYear = group ? group.year_max : DATA.summary.year_max;
      [startInput, endInput].forEach((input) => {
        input.min = minYear || 1980;
        input.max = maxYear || 2019;
        input.step = 1;
      });
      startInput.value = minYear || 1980;
      endInput.value = maxYear || 2019;
      render();
    }
    function syncYears(changed) {
      let start = Number(startInput.value);
      let end = Number(endInput.value);
      if (start > end) {
        if (changed === 'start') endInput.value = start;
        else startInput.value = end;
      }
      render();
    }
    function niceShareCeiling(maxShare) {
      const padded = Math.min(1, Math.max(0.01, Number(maxShare || 0) * 1.05));
      const candidates = [0.01, 0.02, 0.03, 0.04, 0.05, 0.075, 0.1, 0.125, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.75, 1];
      return candidates.find(v => v >= padded) || 1;
    }
    function layoutEndLabels(labels, minY, maxY, gap) {
      labels.sort((a, b) => a.targetY - b.targetY);
      labels.forEach((label, i) => {
        label.y = Math.max(minY, Math.min(maxY, label.targetY));
        if (i && label.y < labels[i - 1].y + gap) label.y = labels[i - 1].y + gap;
      });
      if (labels.length) {
        const overflow = labels[labels.length - 1].y - maxY;
        if (overflow > 0) labels.forEach(label => label.y -= overflow);
        labels[0].y = Math.max(minY, labels[0].y);
        for (let i = 1; i < labels.length; i++) {
          if (labels[i].y < labels[i - 1].y + gap) labels[i].y = labels[i - 1].y + gap;
        }
      }
      return labels;
    }
    function drawChart(group, yearStart, yearEnd) {
      const canvas = document.getElementById('country-chart');
      const ctx = canvas.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      const width = canvas.clientWidth || 1200;
      const height = canvas.clientHeight || 460;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      hoverPoints = [];
      hoverSegments = [];
      if (!group || !group.series.length) {
        ctx.fillStyle = '#666';
        ctx.font = '15px Georgia';
        ctx.fillText('No first-job country data for this selection.', 20, 40);
        return;
      }
      const series = group.series.map(s => ({
        ...s,
        values: s.values.filter(v => v.year >= yearStart && v.year <= yearEnd)
      })).filter(s => s.values.length && !suppressedPlotCountries.has(s.name));
      if (!series.length) {
        ctx.fillStyle = '#666';
        ctx.font = '15px Georgia';
        ctx.fillText('No non-U.S. destination country data for this year range.', 20, 40);
        return;
      }
      const years = [...new Set(series.flatMap(s => s.values.map(v => v.year)))].sort((a,b) => a-b);
      const yMax = niceShareCeiling(Math.max(...series.flatMap(s => s.values.map(v => v.share))));
      const margin = {top: 20, right: 250, bottom: 48, left: 74};
      const plotW = width - margin.left - margin.right;
      const plotH = height - margin.top - margin.bottom;
      const x = (year) => margin.left + (years.length <= 1 ? 0 : (year - years[0]) / (years[years.length - 1] - years[0]) * plotW);
      const y = (share) => margin.top + (1 - Math.min(share, yMax) / yMax) * plotH;
      ctx.strokeStyle = '#ddd7ca';
      ctx.fillStyle = '#666';
      ctx.font = '12px Georgia';
      for (let i = 0; i <= 5; i++) {
        const val = yMax * i / 5;
        const yy = y(val);
        ctx.beginPath();
        ctx.moveTo(margin.left, yy);
        ctx.lineTo(width - margin.right, yy);
        ctx.stroke();
        ctx.fillText(pct(val), 22, yy + 4);
      }
      const tickEvery = Math.max(1, Math.ceil(years.length / 8));
      years.forEach((year, i) => {
        if (i % tickEvery !== 0 && i !== years.length - 1) return;
        ctx.fillText(String(year), x(year) - 13, height - 18);
      });
      const selectedVisible = selectedSeries && series.some(s => s.name === selectedSeries);
      if (!selectedVisible) selectedSeries = null;
      const drawSeries = selectedSeries
        ? [...series.filter(s => s.name !== selectedSeries), ...series.filter(s => s.name === selectedSeries)]
        : series;
      const labelItems = [];
      drawSeries.forEach((s) => {
        const isSelected = !selectedSeries || s.name === selectedSeries;
        ctx.globalAlpha = isSelected ? 1 : 0.22;
        ctx.strokeStyle = isSelected ? s.color : '#3f3f3f';
        ctx.lineWidth = isSelected ? 3.2 : 1.6;
        ctx.beginPath();
        s.values.forEach((v, i) => {
          const xx = x(v.year), yy = y(v.share);
          if (i) ctx.lineTo(xx, yy); else ctx.moveTo(xx, yy);
          if (i) {
            const prev = s.values[i - 1];
            hoverSegments.push({
              x1: x(prev.year),
              y1: y(prev.share),
              x2: xx,
              y2: yy,
              series: s.name
            });
          }
        });
        ctx.stroke();
        ctx.fillStyle = isSelected ? s.color : '#3f3f3f';
        s.values.forEach((v) => {
          const xx = x(v.year), yy = y(v.share);
          ctx.beginPath();
          ctx.arc(xx, yy, isSelected ? 3.6 : 2.4, 0, Math.PI * 2);
          ctx.fill();
          hoverPoints.push({
            x: xx,
            y: yy,
            series: s.name,
            year: v.year,
            share: v.share,
            count: v.count,
            total: v.total,
            breakdown: group.pointBreakdowns[v.year]
          });
        });
        const labelValue = [...s.values].reverse().find(v => v.count > 0) || s.values[s.values.length - 1];
        if (labelValue) labelItems.push({
          label: s.label,
          color: isSelected ? s.color : '#3f3f3f',
          alpha: isSelected ? 1 : 0.35,
          x: x(labelValue.year),
          targetY: y(labelValue.share)
        });
      });
      ctx.globalAlpha = 1;
      const labelX = width - margin.right + 18;
      layoutEndLabels(labelItems, margin.top + 8, height - margin.bottom - 8, 18).forEach(item => {
        ctx.globalAlpha = item.alpha;
        ctx.strokeStyle = item.color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(item.x + 5, item.targetY);
        ctx.lineTo(labelX - 6, item.y);
        ctx.stroke();
        ctx.fillStyle = item.color;
        ctx.fillText(item.label, labelX, item.y + 4);
      });
      ctx.globalAlpha = 1;
    }
    function renderTable(group, yearStart, yearEnd) {
      if (!group) {
        document.getElementById('country-table').innerHTML = '';
        return;
      }
      const totalsByYear = new Map();
      group.series.forEach(s => {
        s.values.forEach(v => {
          if (v.year >= yearStart && v.year <= yearEnd && !totalsByYear.has(v.year)) {
            totalsByYear.set(v.year, v.total);
          }
        });
      });
      const denom = [...totalsByYear.values()].reduce((sum, value) => sum + value, 0);
      const totals = group.series.map(s => {
        let count = 0;
        s.values.forEach(v => {
          if (v.year >= yearStart && v.year <= yearEnd) {
            count += v.count;
          }
        });
        return {country: s.name, count, share: denom ? count / denom : 0};
      }).filter(r => r.count > 0).sort((a,b) => b.count - a.count);
      document.getElementById('country-table').innerHTML = '<table><thead><tr><th>Destination</th><th>Count</th><th>Share across selected years</th></tr></thead><tbody>' +
        totals.map(r => `<tr><td>${r.country}</td><td>${fmt(r.count)}</td><td>${pct(r.share)}</td></tr>`).join('') +
        '</tbody></table>';
    }
    function renderPointDetails(point) {
      if (!point || !point.breakdown || !point.breakdown.countries.length) {
        pointDetails.innerHTML = 'Click a line to isolate that country. Click a point to see the top 7 destination countries for that group and graduation year, including the United States.';
        return;
      }
      const rows = point.breakdown.countries
        .map(r => `<tr><td>${r.country}</td><td>${fmt(r.count)}</td><td>${pct(r.share)}</td></tr>`)
        .join('');
      pointDetails.innerHTML = `<strong>${point.year} destination countries - ${fmt(point.breakdown.total)} users with known country</strong>` +
        '<table><thead><tr><th>Destination</th><th>Count</th><th>Share</th></tr></thead><tbody>' +
        rows +
        '</tbody></table>';
    }
    function nearestPoint(event) {
      const rect = event.target.getBoundingClientRect();
      const mx = event.clientX - rect.left, my = event.clientY - rect.top;
      let best = null, bestDist = 9999;
      hoverPoints.forEach(p => {
        const d = Math.hypot(mx - p.x, my - p.y);
        if (d < bestDist) { best = p; bestDist = d; }
      });
      return {point: best, distance: bestDist, x: mx, y: my};
    }
    function distanceToSegment(px, py, seg) {
      const dx = seg.x2 - seg.x1;
      const dy = seg.y2 - seg.y1;
      const lenSq = dx * dx + dy * dy;
      if (!lenSq) return Math.hypot(px - seg.x1, py - seg.y1);
      const t = Math.max(0, Math.min(1, ((px - seg.x1) * dx + (py - seg.y1) * dy) / lenSq));
      return Math.hypot(px - (seg.x1 + t * dx), py - (seg.y1 + t * dy));
    }
    function nearestSeriesHit(event) {
      const pointHit = nearestPoint(event);
      let bestSegment = null, bestSegmentDist = 9999;
      hoverSegments.forEach(seg => {
        const d = distanceToSegment(pointHit.x, pointHit.y, seg);
        if (d < bestSegmentDist) { bestSegment = seg; bestSegmentDist = d; }
      });
      return {
        ...pointHit,
        segment: bestSegment,
        segmentDistance: bestSegmentDist,
        series: pointHit.distance <= 14 && pointHit.point ? pointHit.point.series : (bestSegmentDist <= 8 && bestSegment ? bestSegment.series : null)
      };
    }
    function render() {
      const group = selectedGroup();
      const start = Number(startInput.value);
      const end = Number(endInput.value);
      startLabel.textContent = start;
      endLabel.textContent = end;
      document.getElementById('chart-title').textContent = group ? group.group : '';
      const horizon = selectedHorizon();
      document.getElementById('chart-subtitle').textContent = group ? `${horizon.label} - ${viewSelect.options[viewSelect.selectedIndex].text} - ${fmt(group.n)} PhDs with known country` : '';
      drawChart(group, start, end);
      renderTable(group, start, end);
      renderPointDetails(null);
    }
    document.getElementById('country-chart').addEventListener('mousemove', (event) => {
      const hit = nearestPoint(event);
      if (!hit.point || hit.distance > 12) {
        tooltip.style.opacity = 0;
        return;
      }
      tooltip.innerHTML = `<strong>${hit.point.series}</strong><br>${hit.point.year}: ${pct(hit.point.share)}<br>${fmt(hit.point.count)} / ${fmt(hit.point.total)}<br>Click for country list`;
      tooltip.style.left = hit.x + 'px';
      tooltip.style.top = hit.y + 'px';
      tooltip.style.opacity = 1;
    });
    document.getElementById('country-chart').addEventListener('click', (event) => {
      const hit = nearestSeriesHit(event);
      selectedSeries = hit.series;
      render();
      if (hit.point && hit.distance <= 14) renderPointDetails(hit.point);
    });
    document.getElementById('country-chart').addEventListener('mouseleave', () => tooltip.style.opacity = 0);
    horizonSelect.addEventListener('change', () => { selectedSeries = null; setStats(); fillGroups(); });
    viewSelect.addEventListener('change', () => { selectedSeries = null; fillGroups(); });
    groupSelect.addEventListener('change', () => { selectedSeries = null; updateYearBounds(); });
    startInput.addEventListener('input', () => syncYears('start'));
    endInput.addEventListener('input', () => syncYears('end'));
    window.addEventListener('resize', render);
    fillHorizons();
    setStats();
    fillGroups();
  </script>
""".replace("__DATA__", data_json)
    html = common.html_shell(
        "International Migration of Non-US PhDs",
        "Destination countries immediately after the PhD, 3 years later, and 5 years later among PhD recipients whose bachelor degree was outside the United States.",
        body,
        script,
    )
    common.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(html, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, diagnostics = load_non_us_bachelor_rows()
    common.write_csv(
        USER_CSV,
        [
            "rev_user_id",
            "goid",
            "grad_year",
            "nsf_broad",
            "nsf_major",
            "nsf_primary",
            "phd_institution",
            "phd_institution_norm",
            "carnegie_unitid",
            "bachelor_country",
            "bachelor_university",
            "bachelor_country_source",
            "bachelor_degree_signal",
            "first_job_country",
            "first_job_country_group",
            "first_job_startdate",
            "first_job_org_type",
            "company_cleaned",
            "company_raw",
            "year_3_country",
            "year_3_country_group",
            "year_3_start_dt",
            "year_3_end_dt",
            "year_3_job_start_year",
            "year_3_job_end_year",
            "year_3_job_order",
            "year_3_position_id",
            "year_3_company_cleaned",
            "year_3_company_raw",
            "year_5_country",
            "year_5_country_group",
            "year_5_start_dt",
            "year_5_end_dt",
            "year_5_job_start_year",
            "year_5_job_end_year",
            "year_5_job_order",
            "year_5_position_id",
            "year_5_company_cleaned",
            "year_5_company_raw",
        ],
        rows,
    )
    payload, aggregate_rows = build_dashboard_payload(rows, diagnostics)
    common.write_csv(
        AGG_CSV,
        [
            "horizon",
            "view",
            "group",
            "destination",
            "year",
            "count",
            "total_with_country",
            "share",
        ],
        aggregate_rows,
    )
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_page(payload)
    summary = payload["summary"]
    print(f"Wrote {DOC_PATH}")
    for horizon_key, horizon_label, _offset in HORIZONS:
        print(
            f"{horizon_label} countries for non-US bachelor origins through "
            f"{summary['max_dashboard_year']}: "
            f"{summary[f'display_with_{horizon_key}_country']:,}/"
            f"{summary['display_non_us_bachelor_users']:,} displayed users with known country"
        )


if __name__ == "__main__":
    main()
