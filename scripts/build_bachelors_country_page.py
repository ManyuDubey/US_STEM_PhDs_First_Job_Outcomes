#!/usr/bin/env python3
"""Build bachelor-degree country summaries for the published dashboard."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from typing import Dict

import dashboard_data_common as common


OUT_DIR = common.OUTPUT_DIR / "bachelors_countries"
SUMMARY_JSON = OUT_DIR / "summary.json"
USER_CSV = OUT_DIR / "bachelor_country_by_user.csv"
AGG_CSV = OUT_DIR / "bachelor_country_top10_groups.csv"
DOC_PATH = common.DOCS_DIR / "bachelors_countries.html"


def selected_degree_rows() -> tuple[list[Dict[str, str]], Counter]:
    users = common.load_first_job_users()
    by_user, by_goid = common.index_degree_rows(users)
    output: list[Dict[str, str]] = []
    diagnostics: Counter = Counter()

    for user_id, info in users.items():
        phd_row, phd_source = common.choose_phd_row(info, by_user, by_goid)
        bachelor_row, bachelor_source = common.choose_bachelor_row(info, by_user, by_goid)
        phd_inst = common.degree_university(phd_row) if phd_row else ""
        bachelor_inst = common.degree_university(bachelor_row) if bachelor_row else ""
        bachelor_country = ""
        country_source = "missing"
        if bachelor_row:
            bachelor_country, country_source = common.country_from_degree_row(bachelor_row)
            diagnostics["users_with_bachelor_row"] += 1
            if bachelor_country:
                diagnostics["users_with_bachelor_country"] += 1
            else:
                diagnostics["users_with_bachelor_missing_country"] += 1
        else:
            diagnostics["users_without_bachelor_row"] += 1
        if phd_row:
            diagnostics["users_with_phd_row"] += 1
        else:
            diagnostics["users_without_phd_row"] += 1

        output.append(
            {
                "rev_user_id": user_id,
                "goid": info.get("goid", ""),
                "grad_year": info.get("grad_year", ""),
                "nsf_broad": info.get("nsf_broad", ""),
                "nsf_major": info.get("nsf_major", ""),
                "nsf_primary": info.get("nsf_primary", ""),
                "phd_institution": phd_inst,
                "phd_institution_norm": common.norm_institution(phd_inst),
                "phd_country": common.country_from_degree_row(phd_row)[0] if phd_row else "",
                "phd_selection_source": phd_source,
                "bachelor_university": bachelor_inst,
                "bachelor_country": bachelor_country,
                "bachelor_country_source": country_source,
                "bachelor_selection_source": bachelor_source,
                "bachelor_degree": common.clean(bachelor_row.get("degree")) if bachelor_row else "",
                "bachelor_degree_raw": common.clean(bachelor_row.get("degree_raw")) if bachelor_row else "",
                "bachelor_end_year": common.clean(bachelor_row.get("edu_end_year")) if bachelor_row else "",
            }
        )

    diagnostics["total_users"] = len(users)
    return output, diagnostics


def top10(counter: Counter, min_count: int = 1) -> list[Dict[str, object]]:
    return [
        {"country": country, "count": count}
        for country, count in counter.most_common(10)
        if country and country.lower() != "empty" and count >= min_count
    ]


def build_groups(rows: list[Dict[str, str]]) -> tuple[dict[str, list[Dict[str, object]]], list[Dict[str, object]]]:
    dimensions = {
        "overall": defaultdict(Counter),
        "nsf_broad": defaultdict(Counter),
        "nsf_major": defaultdict(Counter),
        "nsf_primary": defaultdict(Counter),
        "phd_university": defaultdict(Counter),
        "phd_university_x_broad": defaultdict(Counter),
    }
    totals: dict[str, Counter] = {name: Counter() for name in dimensions}

    for row in rows:
        country = row.get("bachelor_country", "")
        if not country:
            continue
        keys = {
            "overall": "All fields",
            "nsf_broad": row.get("nsf_broad", ""),
            "nsf_major": row.get("nsf_major", ""),
            "nsf_primary": row.get("nsf_primary", ""),
            "phd_university": row.get("phd_institution", ""),
            "phd_university_x_broad": " | ".join(
                part for part in [row.get("phd_institution", ""), row.get("nsf_broad", "")] if part
            ),
        }
        for dim, key in keys.items():
            if not key:
                continue
            dimensions[dim][key][country] += 1
            totals[dim][key] += 1

    payload: dict[str, list[Dict[str, object]]] = {}
    agg_rows: list[Dict[str, object]] = []
    for dim, groups in dimensions.items():
        min_group = 1
        limit = None
        if dim == "phd_university":
            min_group = 40
            limit = 350
        elif dim == "phd_university_x_broad":
            min_group = 30
            limit = 500
        sorted_groups = sorted(groups.items(), key=lambda item: sum(item[1].values()), reverse=True)
        entries: list[Dict[str, object]] = []
        for key, counts in sorted_groups:
            group_total = sum(counts.values())
            if group_total < min_group:
                continue
            item = {
                "group": key,
                "n_with_country": group_total,
                "top_countries": top10(counts),
            }
            entries.append(item)
            for rank, country_row in enumerate(item["top_countries"], start=1):
                agg_rows.append(
                    {
                        "dimension": dim,
                        "group": key,
                        "n_with_country": group_total,
                        "rank": rank,
                        "country": country_row["country"],
                        "count": country_row["count"],
                        "share": round(country_row["count"] / group_total, 5) if group_total else 0,
                    }
                )
            if limit and len(entries) >= limit:
                break
        payload[dim] = entries
    return payload, agg_rows


def write_page(payload: dict[str, object]) -> None:
    data_json = json.dumps(payload)
    body = """
    <div class="card"><div id="stats" class="stats"></div></div>
    <div class="card">
      <div class="controls">
        <div class="control">
          <label for="dimension-select">Breakout</label>
          <select id="dimension-select"></select>
        </div>
        <div class="control">
          <label for="group-select">Field or university</label>
          <select id="group-select"></select>
        </div>
      </div>
      <canvas id="country-chart" class="chart"></canvas>
      <div class="note">Bachelor rows are Revelio bachelor records plus conservative undergraduate-degree fallbacks. Countries come from degree institution country first, then location text when needed.</div>
    </div>
    <div class="card">
      <h2>Top Countries Table</h2>
      <div id="country-table"></div>
    </div>
    """
    script = f"""
  <script>
    const DATA = {data_json};
    const LABELS = {{
      overall: 'Overall',
      nsf_broad: 'NSF broad field',
      nsf_major: 'NSF major field',
      nsf_primary: 'NSF primary field',
      phd_university: 'PhD university',
      phd_university_x_broad: 'PhD university x broad field'
    }};
    function fmt(n) {{ return Number(n).toLocaleString(); }}
    function pct(x) {{ return (Number(x) * 100).toFixed(1) + '%'; }}
    function draw(rows, title, total) {{
      const canvas = document.getElementById('country-chart');
      const ctx = canvas.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth || 1100, h = canvas.clientHeight || 460;
      canvas.width = w * dpr; canvas.height = h * dpr; ctx.setTransform(dpr,0,0,dpr,0,0);
      ctx.clearRect(0,0,w,h);
      const margin = {{left:190,right:90,top:34,bottom:24}};
      const maxVal = Math.max(...rows.map(r => r.count), 1);
      const barH = Math.min(31, (h-margin.top-margin.bottom)/Math.max(rows.length,1)-7);
      ctx.font = '13px Georgia';
      rows.forEach((r,i) => {{
        const y = margin.top + i*(barH+7);
        const bw = r.count / maxVal * (w-margin.left-margin.right);
        ctx.fillStyle = '#1f4e79'; ctx.fillRect(margin.left, y, bw, barH);
        ctx.fillStyle = '#222'; ctx.fillText(r.country, 12, y + barH*0.7);
        ctx.fillText(fmt(r.count) + ' (' + pct(r.count/total) + ')', margin.left + bw + 8, y + barH*0.7);
      }});
      ctx.fillStyle = '#222'; ctx.font = '16px Georgia'; ctx.fillText(title, margin.left, 18);
    }}
    function table(rows, total) {{
      return '<table><thead><tr><th>Rank</th><th>Country</th><th>Count</th><th>Share</th></tr></thead><tbody>' +
        rows.map((r,i) => `<tr><td>${{i+1}}</td><td>${{r.country}}</td><td>${{fmt(r.count)}}</td><td>${{pct(r.count/total)}}</td></tr>`).join('') +
        '</tbody></table>';
    }}
    function init() {{
      const s = DATA.summary;
      document.getElementById('stats').innerHTML = [
        ['Users', fmt(s.total_users)],
        ['With bachelor row', fmt(s.users_with_bachelor_row)],
        ['With bachelor country', fmt(s.users_with_bachelor_country)],
        ['Missing bachelor country', fmt(s.users_with_bachelor_missing_country)]
      ].map(([label,value]) => `<div class="stat"><div class="value">${{value}}</div><div class="label">${{label}}</div></div>`).join('');
      const dim = document.getElementById('dimension-select');
      const group = document.getElementById('group-select');
      dim.innerHTML = Object.keys(LABELS).map(k => `<option value="${{k}}">${{LABELS[k]}}</option>`).join('');
      function fillGroups() {{
        const items = DATA.groups[dim.value] || [];
        group.innerHTML = items.map((d,i) => `<option value="${{i}}">${{d.group}} (${{fmt(d.n_with_country)}})</option>`).join('');
        render();
      }}
      function render() {{
        const items = DATA.groups[dim.value] || [];
        const item = items[Number(group.value || 0)];
        if (!item) return;
        draw(item.top_countries, item.group, item.n_with_country);
        document.getElementById('country-table').innerHTML = table(item.top_countries, item.n_with_country);
      }}
      dim.addEventListener('change', fillGroups);
      group.addEventListener('change', render);
      fillGroups();
    }}
    init();
  </script>
"""
    html = common.html_shell(
        "Bachelor Degree Countries",
        "Top supplying countries for bachelor degrees among matched PhDs, by field and PhD university.",
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
        "phd_country",
        "phd_selection_source",
        "bachelor_university",
        "bachelor_country",
        "bachelor_country_source",
        "bachelor_selection_source",
        "bachelor_degree",
        "bachelor_degree_raw",
        "bachelor_end_year",
    ]
    common.write_csv(USER_CSV, fieldnames, rows)
    groups, agg_rows = build_groups(rows)
    common.write_csv(
        AGG_CSV,
        ["dimension", "group", "n_with_country", "rank", "country", "count", "share"],
        agg_rows,
    )
    payload = {"summary": dict(diagnostics), "groups": groups}
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_page(payload)
    print(f"Wrote {DOC_PATH}")
    print(
        "Bachelor countries: "
        f"{diagnostics['users_with_bachelor_country']:,}/{diagnostics['total_users']:,} users"
    )


if __name__ == "__main__":
    main()
