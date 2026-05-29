#!/usr/bin/env python3
"""Build bachelor-degree country time-series dashboard."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from typing import Dict

import dashboard_data_common as common


OUT_DIR = common.OUTPUT_DIR / "bachelors_countries"
SUMMARY_JSON = OUT_DIR / "summary.json"
USER_CSV = OUT_DIR / "bachelor_country_by_user.csv"
AGG_CSV = OUT_DIR / "bachelor_country_time_series.csv"
DOC_PATH = common.DOCS_DIR / "bachelors_countries.html"
NSF_CROSSWALK = common.CODEX_DATA / "goid_user_id_nsf.csv"
MIN_BROAD_GROUP_WITH_COUNTRY = 25
MIN_MAJOR_GROUP_WITH_COUNTRY = 40

EXCLUDED_BROAD_FIELDS = {
    "business",
    "education",
    "humanities and arts",
    "other non science and engineering",
    "psychology",
    "social sciences",
}

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


def load_carnegie_nsf_map() -> tuple[dict[tuple[str, str], Dict[str, str]], Counter]:
    raw: dict[tuple[str, str], set[tuple[str, str, str, str, str]]] = defaultdict(set)
    with NSF_CROSSWALK.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            goid = common.norm_id(row.get("goid"))
            user_id = common.norm_id(row.get("rev_user_id"))
            if not goid or not user_id:
                continue
            raw[(goid, user_id)].add(
                (
                    common.clean(row.get("carnegie_name")),
                    common.norm_id(row.get("carnegie_unitid")),
                    common.clean(row.get("nsf_primary")),
                    common.clean(row.get("nsf_major")),
                    common.clean(row.get("nsf_broad")),
                )
            )

    out: dict[tuple[str, str], Dict[str, str]] = {}
    diagnostics: Counter = Counter()
    for key, values in raw.items():
        diagnostics["crosswalk_pair_keys"] += 1
        compact = {(name, primary, major, broad) for name, _unitid, primary, major, broad in values}
        if len(compact) != 1:
            diagnostics["crosswalk_ambiguous_pairs"] += 1
            continue
        name, primary, major, broad = next(iter(compact))
        unitids = sorted({unitid for _name, unitid, _primary, _major, _broad in values if unitid})
        out[key] = {
            "carnegie_name": name,
            "carnegie_unitid": "|".join(unitids),
            "nsf_primary": primary,
            "nsf_major": major,
            "nsf_broad": broad,
        }
        diagnostics["crosswalk_safe_pairs"] += 1
    return out, diagnostics


def selected_degree_rows() -> tuple[list[Dict[str, str]], Counter]:
    users = common.load_first_job_users()
    carnegie_map, diagnostics = load_carnegie_nsf_map()
    by_user, by_goid = common.index_degree_rows(users)
    institution_country_map = common.build_unique_institution_country_map(users)
    diagnostics["unique_institution_country_keys"] = len(institution_country_map)
    output: list[Dict[str, str]] = []

    for user_id, info in users.items():
        goid = info.get("goid", "")
        grad_year = common.to_int(info.get("grad_year"))
        if grad_year is None:
            diagnostics["missing_grad_year"] += 1
            continue

        carnegie = carnegie_map.get((goid, user_id))
        if not carnegie:
            diagnostics["missing_carnegie_crosswalk_row"] += 1
            continue

        nsf_broad = carnegie.get("nsf_broad", "") or info.get("nsf_broad", "")
        if common.norm_label(nsf_broad) in EXCLUDED_BROAD_FIELDS:
            diagnostics["excluded_non_stem_or_social_science_users"] += 1
            continue

        bachelor_row, bachelor_source = common.choose_bachelor_row(
            info,
            by_user,
            by_goid,
            institution_country_map,
        )
        bachelor_inst = common.degree_university(bachelor_row) if bachelor_row else ""
        bachelor_country = ""
        country_source = "missing"
        bachelor_signal = ""
        if bachelor_row:
            bachelor_country, country_source = common.infer_country_from_degree_row(
                bachelor_row,
                institution_country_map,
            )
            bachelor_signal = common.bachelor_degree_signal(bachelor_row)
            diagnostics["users_with_bachelor_row"] += 1
            diagnostics[f"bachelor_signal_{bachelor_signal or 'unknown'}"] += 1
            diagnostics[f"bachelor_country_source_{country_source}"] += 1
            if bachelor_country:
                diagnostics["users_with_bachelor_country"] += 1
            else:
                diagnostics["users_with_bachelor_missing_country"] += 1
        else:
            diagnostics["users_without_bachelor_row"] += 1

        diagnostics["included_users"] += 1
        output.append(
            {
                "rev_user_id": user_id,
                "goid": goid,
                "grad_year": str(grad_year),
                "nsf_broad": nsf_broad,
                "nsf_major": carnegie.get("nsf_major", "") or info.get("nsf_major", ""),
                "nsf_primary": carnegie.get("nsf_primary", "") or info.get("nsf_primary", ""),
                "phd_institution": carnegie.get("carnegie_name", ""),
                "phd_institution_norm": common.norm_institution(carnegie.get("carnegie_name", "")),
                "carnegie_unitid": carnegie.get("carnegie_unitid", ""),
                "phd_selection_source": "goid_user_id_nsf_carnegie",
                "bachelor_university": bachelor_inst,
                "bachelor_country": bachelor_country,
                "bachelor_country_source": country_source,
                "bachelor_selection_source": bachelor_source,
                "bachelor_degree_signal": bachelor_signal,
                "bachelor_degree": common.clean(bachelor_row.get("degree")) if bachelor_row else "",
                "bachelor_degree_raw": common.clean(bachelor_row.get("degree_raw")) if bachelor_row else "",
                "bachelor_end_year": common.clean(bachelor_row.get("edu_end_year")) if bachelor_row else "",
            }
        )

    diagnostics["total_users"] = len(users)
    return output, diagnostics


def country_rank(counts: Counter, limit: int = 10) -> list[str]:
    return [country for country, _count in counts.most_common(limit) if country]


def series_for_group(
    by_year_country: dict[int, Counter],
    top_countries: list[str],
) -> list[Dict[str, object]]:
    years = sorted(by_year_country)
    series: list[Dict[str, object]] = []
    countries = list(top_countries)
    other_total = sum(
        count
        for counter in by_year_country.values()
        for country, count in counter.items()
        if country not in top_countries
    )
    if other_total:
        countries.append("Other countries")

    for idx, country in enumerate(countries):
        values = []
        for year in years:
            counter = by_year_country[year]
            denom = sum(counter.values())
            if country == "Other countries":
                count = sum(count for c, count in counter.items() if c not in top_countries)
            else:
                count = counter.get(country, 0)
            values.append(
                {
                    "year": year,
                    "count": count,
                    "share": round(count / denom, 6) if denom else 0,
                    "total": denom,
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
    universities: dict[str, Dict[str, object]] = {}
    aggregates: list[Dict[str, object]] = []
    buckets: dict[str, dict[str, dict[str, dict[int, Counter]]]] = defaultdict(
        lambda: {
            "overall": defaultdict(lambda: defaultdict(Counter)),
            "broad": defaultdict(lambda: defaultdict(Counter)),
            "major": defaultdict(lambda: defaultdict(Counter)),
        }
    )
    university_labels: dict[str, str] = {}
    university_unitids: dict[str, str] = {}

    for row in rows:
        country = row.get("bachelor_country", "")
        if not country:
            continue
        inst_norm = row.get("phd_institution_norm", "")
        if not inst_norm:
            continue
        year = common.to_int(row.get("grad_year"))
        if year is None:
            continue
        university_labels.setdefault(inst_norm, row.get("phd_institution", inst_norm))
        university_unitids.setdefault(inst_norm, row.get("carnegie_unitid", ""))
        buckets[inst_norm]["overall"]["All STEM fields"][year][country] += 1
        if row.get("nsf_broad"):
            buckets[inst_norm]["broad"][row["nsf_broad"]][year][country] += 1
        if row.get("nsf_major"):
            buckets[inst_norm]["major"][row["nsf_major"]][year][country] += 1

    for inst_norm, views in buckets.items():
        total_with_country = sum(
            sum(counter.values())
            for by_year in views["overall"]["All STEM fields"].values()
            for counter in [by_year]
        )
        if total_with_country <= 0:
            continue
        university: Dict[str, object] = {
            "id": inst_norm,
            "name": university_labels.get(inst_norm, inst_norm),
            "carnegie_unitid": university_unitids.get(inst_norm, ""),
            "n_with_country": total_with_country,
            "views": {"overall": [], "broad": [], "major": []},
        }
        for view_name, groups in views.items():
            entries = []
            for group_name, by_year_country in groups.items():
                group_total = sum(sum(counter.values()) for counter in by_year_country.values())
                if group_total <= 0:
                    continue
                if view_name == "broad" and group_total < MIN_BROAD_GROUP_WITH_COUNTRY:
                    continue
                if view_name == "major" and group_total < MIN_MAJOR_GROUP_WITH_COUNTRY:
                    continue
                top = country_rank(Counter({
                    country: sum(counter.get(country, 0) for counter in by_year_country.values())
                    for counter in by_year_country.values()
                    for country in counter
                }))
                series = series_for_group(by_year_country, top)
                entries.append(
                    {
                        "field": group_name,
                        "n_with_country": group_total,
                        "year_min": min(by_year_country),
                        "year_max": max(by_year_country),
                        "series": series,
                    }
                )
                for serie in series:
                    for value in serie["values"]:
                        aggregates.append(
                            {
                                "university": university["name"],
                                "carnegie_unitid": university["carnegie_unitid"],
                                "view": view_name,
                                "field": group_name,
                                "country": serie["name"],
                                "year": value["year"],
                                "count": value["count"],
                                "total_with_country": value["total"],
                                "share": value["share"],
                            }
                        )
            entries.sort(key=lambda item: (-int(item["n_with_country"]), str(item["field"])))
            university["views"][view_name] = entries
        universities[inst_norm] = university

    university_list = sorted(
        universities.values(),
        key=lambda item: (-int(item["n_with_country"]), str(item["name"])),
    )
    all_years = sorted(
        {
            int(value["year"])
            for row in university_list
            for groups in row["views"].values()
            for group in groups
            for serie in group["series"]
            for value in serie["values"]
        }
    )
    compact_universities = []
    for university in university_list:
        compact_views = {}
        views = university["views"]
        for view_name in ["overall", "broad", "major"]:
            compact_groups = []
            for group in views[view_name]:
                compact_series = []
                for serie in group["series"]:
                    compact_values = [
                        [value["year"], value["count"], value["total"]]
                        for value in serie["values"]
                    ]
                    compact_series.append([serie["name"], serie["label"], serie["color"], compact_values])
                compact_groups.append(
                    [
                        group["field"],
                        group["n_with_country"],
                        group["year_min"],
                        group["year_max"],
                        compact_series,
                    ]
                )
            compact_views[view_name] = compact_groups
        compact_universities.append(
            [
                university["name"],
                university["carnegie_unitid"],
                university["n_with_country"],
                compact_views,
            ]
        )

    payload = {
        "summary": {
            **dict(diagnostics),
            "excluded_broad_fields": sorted(EXCLUDED_BROAD_FIELDS),
            "min_broad_group_with_country": MIN_BROAD_GROUP_WITH_COUNTRY,
            "min_major_group_with_country": MIN_MAJOR_GROUP_WITH_COUNTRY,
            "universities": len(university_list),
            "year_min": min(all_years) if all_years else None,
            "year_max": max(all_years) if all_years else None,
        },
        "universities": compact_universities,
    }
    return payload, aggregates


def write_page(payload: dict[str, object]) -> None:
    data_json = json.dumps(payload)
    body = """
    <div class="card"><div id="stats" class="stats"></div></div>
    <div class="card">
      <div class="controls">
        <div class="control">
          <label for="university-select">PhD university</label>
          <select id="university-select"></select>
        </div>
        <div class="control">
          <label for="view-select">View</label>
          <select id="view-select">
            <option value="overall">University overall</option>
            <option value="broad">NSF broad field</option>
            <option value="major">NSF major field</option>
          </select>
        </div>
        <div class="control">
          <label for="field-select">Field</label>
          <select id="field-select"></select>
        </div>
        <div class="control">
          <label for="year-start">Start year</label>
          <input id="year-start" type="range">
          <span id="year-start-label" class="range-value"></span>
        </div>
        <div class="control">
          <label for="year-end">End year</label>
          <input id="year-end" type="range">
          <span id="year-end-label" class="range-value"></span>
        </div>
      </div>
      <div id="chart-title" class="title"></div>
      <div id="chart-subtitle" class="subtitle"></div>
      <div class="chart-box">
        <canvas id="country-chart" class="chart"></canvas>
        <div id="tooltip" class="tooltip"></div>
      </div>
      <div class="note">Uses Carnegie PhD university names from codex_data/goid_user_id_nsf.csv. Social sciences, education, psychology, business, humanities and arts, and other non-science fields are excluded. Percentages use users with an identified bachelor country as the denominator.</div>
    </div>
    <div class="card">
      <h2>Country Summary</h2>
      <div id="country-table"></div>
    </div>
    """
    script = f"""
  <script>
    const DATA = {data_json};
    const universities = DATA.universities || [];
    const fmt = (n) => Number(n || 0).toLocaleString();
    const pct = (x) => (Number(x || 0) * 100).toFixed(1) + '%';
    const universitySelect = document.getElementById('university-select');
    const viewSelect = document.getElementById('view-select');
    const fieldSelect = document.getElementById('field-select');
    const startInput = document.getElementById('year-start');
    const endInput = document.getElementById('year-end');
    const startLabel = document.getElementById('year-start-label');
    const endLabel = document.getElementById('year-end-label');
    const tooltip = document.getElementById('tooltip');
    let hoverPoints = [];

    function unpackUniversity(u) {{
      if (!u) return null;
      return {{name: u[0], carnegie_unitid: u[1], n_with_country: u[2], views: u[3]}};
    }}
    function unpackGroup(g) {{
      if (!g) return null;
      return {{
        field: g[0],
        n_with_country: g[1],
        year_min: g[2],
        year_max: g[3],
        series: (g[4] || []).map(s => ({{
          name: s[0],
          label: s[1],
          color: s[2],
          values: (s[3] || []).map(v => ({{
            year: v[0],
            count: v[1],
            total: v[2],
            share: v[2] ? v[1] / v[2] : 0
          }}))
        }}))
      }};
    }}
    function groupsForSelectedView() {{
      const uni = selectedUniversity();
      return ((uni && uni.views[viewSelect.value]) || []).map(unpackGroup);
    }}
    function selectedUniversity() {{
      return unpackUniversity(universities[Number(universitySelect.value || 0)]);
    }}
    function selectedGroup() {{
      const groups = groupsForSelectedView();
      return groups[Number(fieldSelect.value || 0)];
    }}
    function setStats() {{
      const s = DATA.summary || {{}};
      document.getElementById('stats').innerHTML = [
        ['Included STEM users', fmt(s.included_users)],
        ['With bachelor country', fmt(s.users_with_bachelor_country)],
        ['Universities', fmt(s.universities)],
        ['Excluded fields', fmt(s.excluded_non_stem_or_social_science_users)]
      ].map(([label,value]) => `<div class="stat"><div class="value">${{value}}</div><div class="label">${{label}}</div></div>`).join('');
    }}
    function fillUniversities() {{
      universitySelect.innerHTML = universities.map((u, i) => `<option value="${{i}}">${{u[0]}} (${{fmt(u[2])}})</option>`).join('');
    }}
    function fillFields() {{
      const groups = groupsForSelectedView();
      fieldSelect.disabled = viewSelect.value === 'overall';
      fieldSelect.innerHTML = groups.map((g, i) => `<option value="${{i}}">${{g.field}} (${{fmt(g.n_with_country)}})</option>`).join('');
      if (!groups.length) {{
        fieldSelect.innerHTML = '<option value="0">No data</option>';
      }}
      updateYearBounds();
    }}
    function updateYearBounds() {{
      const group = selectedGroup();
      const minYear = group ? group.year_min : DATA.summary.year_min;
      const maxYear = group ? group.year_max : DATA.summary.year_max;
      [startInput, endInput].forEach((input) => {{
        input.min = minYear;
        input.max = maxYear;
        input.step = 1;
      }});
      startInput.value = minYear;
      endInput.value = maxYear;
      render();
    }}
    function syncYears(changed) {{
      let start = Number(startInput.value);
      let end = Number(endInput.value);
      if (start > end) {{
        if (changed === 'start') endInput.value = start;
        else startInput.value = end;
      }}
      render();
    }}
    function drawChart(group, yearStart, yearEnd) {{
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
      if (!group || !group.series.length) {{
        ctx.fillStyle = '#666';
        ctx.font = '15px Georgia';
        ctx.fillText('No bachelor-country data for this selection.', 20, 40);
        return;
      }}
      const series = group.series.map(s => ({{
        ...s,
        values: s.values.filter(v => v.year >= yearStart && v.year <= yearEnd)
      }})).filter(s => s.values.length);
      const years = [...new Set(series.flatMap(s => s.values.map(v => v.year)))].sort((a,b) => a-b);
      const margin = {{top: 20, right: 260, bottom: 48, left: 74}};
      const plotW = width - margin.left - margin.right;
      const plotH = height - margin.top - margin.bottom;
      const x = (year) => margin.left + (years.length <= 1 ? 0 : (year - years[0]) / (years[years.length - 1] - years[0]) * plotW);
      const y = (share) => margin.top + (1 - share) * plotH;
      ctx.strokeStyle = '#ddd7ca';
      ctx.fillStyle = '#666';
      ctx.font = '12px Georgia';
      for (let i = 0; i <= 5; i++) {{
        const val = i / 5;
        const yy = y(val);
        ctx.beginPath();
        ctx.moveTo(margin.left, yy);
        ctx.lineTo(width - margin.right, yy);
        ctx.stroke();
        ctx.fillText(Math.round(val * 100) + '%', 22, yy + 4);
      }}
      const tickEvery = Math.max(1, Math.ceil(years.length / 8));
      years.forEach((year, i) => {{
        if (i % tickEvery !== 0 && i !== years.length - 1) return;
        ctx.fillText(String(year), x(year) - 13, height - 18);
      }});
      series.forEach((s, idx) => {{
        ctx.strokeStyle = s.color;
        ctx.lineWidth = 2.3;
        ctx.beginPath();
        s.values.forEach((v, i) => {{
          const xx = x(v.year), yy = y(v.share);
          if (i) ctx.lineTo(xx, yy); else ctx.moveTo(xx, yy);
        }});
        ctx.stroke();
        ctx.fillStyle = s.color;
        s.values.forEach((v) => {{
          const xx = x(v.year), yy = y(v.share);
          ctx.beginPath();
          ctx.arc(xx, yy, 3, 0, Math.PI * 2);
          ctx.fill();
          hoverPoints.push({{x: xx, y: yy, series: s.name, year: v.year, share: v.share, count: v.count, total: v.total}});
        }});
        const last = s.values[s.values.length - 1];
        if (last) {{
          ctx.fillText(s.label, width - margin.right + 18, y(last.share) + 4);
        }}
      }});
    }}
    function renderTable(group, yearStart, yearEnd) {{
      if (!group) {{
        document.getElementById('country-table').innerHTML = '';
        return;
      }}
      const totals = group.series.map(s => {{
        let count = 0, denom = 0;
        s.values.forEach(v => {{
          if (v.year >= yearStart && v.year <= yearEnd) {{
            count += v.count;
            denom += v.total;
          }}
        }});
        return {{country: s.name, count, share: denom ? count / denom : 0}};
      }}).filter(r => r.count > 0).sort((a,b) => b.count - a.count);
      document.getElementById('country-table').innerHTML = '<table><thead><tr><th>Country</th><th>Count</th><th>Share across selected years</th></tr></thead><tbody>' +
        totals.map(r => `<tr><td>${{r.country}}</td><td>${{fmt(r.count)}}</td><td>${{pct(r.share)}}</td></tr>`).join('') +
        '</tbody></table>';
    }}
    function render() {{
      const uni = selectedUniversity();
      const group = selectedGroup();
      const start = Number(startInput.value);
      const end = Number(endInput.value);
      startLabel.textContent = start;
      endLabel.textContent = end;
      document.getElementById('chart-title').textContent = uni ? uni.name : '';
      document.getElementById('chart-subtitle').textContent = group ? `${{viewSelect.options[viewSelect.selectedIndex].text}} · ${{group.field}} · ${{fmt(group.n_with_country)}} PhDs with bachelor country` : '';
      drawChart(group, start, end);
      renderTable(group, start, end);
    }}
    document.getElementById('country-chart').addEventListener('mousemove', (event) => {{
      const rect = event.target.getBoundingClientRect();
      const mx = event.clientX - rect.left, my = event.clientY - rect.top;
      let best = null, bestDist = 9999;
      hoverPoints.forEach(p => {{
        const d = Math.hypot(mx - p.x, my - p.y);
        if (d < bestDist) {{ best = p; bestDist = d; }}
      }});
      if (!best || bestDist > 12) {{
        tooltip.style.opacity = 0;
        return;
      }}
      tooltip.innerHTML = `<strong>${{best.series}}</strong><br>${{best.year}}: ${{pct(best.share)}}<br>${{fmt(best.count)}} / ${{fmt(best.total)}}`;
      tooltip.style.left = mx + 'px';
      tooltip.style.top = my + 'px';
      tooltip.style.opacity = 1;
    }});
    document.getElementById('country-chart').addEventListener('mouseleave', () => tooltip.style.opacity = 0);
    universitySelect.addEventListener('change', fillFields);
    viewSelect.addEventListener('change', fillFields);
    fieldSelect.addEventListener('change', updateYearBounds);
    startInput.addEventListener('input', () => syncYears('start'));
    endInput.addEventListener('input', () => syncYears('end'));
    window.addEventListener('resize', render);
    setStats();
    fillUniversities();
    fillFields();
  </script>
"""
    html = common.html_shell(
        "Bachelor Degree Countries",
        "Bachelor-country composition over time for PhD recipients by Carnegie university and NSF field.",
        body,
        script,
    )
    common.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(html, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, diagnostics = selected_degree_rows()
    fieldnames = [
        "rev_user_id",
        "goid",
        "grad_year",
        "nsf_broad",
        "nsf_major",
        "nsf_primary",
        "phd_institution",
        "phd_institution_norm",
        "carnegie_unitid",
        "phd_selection_source",
        "bachelor_university",
        "bachelor_country",
        "bachelor_country_source",
        "bachelor_selection_source",
        "bachelor_degree_signal",
        "bachelor_degree",
        "bachelor_degree_raw",
        "bachelor_end_year",
    ]
    common.write_csv(USER_CSV, fieldnames, rows)
    payload, aggregate_rows = build_dashboard_payload(rows, diagnostics)
    common.write_csv(
        AGG_CSV,
        [
            "university",
            "carnegie_unitid",
            "view",
            "field",
            "country",
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
    print(
        "Bachelor countries: "
        f"{summary['users_with_bachelor_country']:,}/{summary['included_users']:,} included STEM users"
    )


if __name__ == "__main__":
    main()
