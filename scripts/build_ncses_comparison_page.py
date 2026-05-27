#!/usr/bin/env python3
"""Build the NCSES comparison page for the published dashboard."""

from __future__ import annotations

import csv
import difflib
import io
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict

import dashboard_data_common as common


OUT_DIR = common.OUTPUT_DIR / "ncses_comparison"
SUMMARY_JSON = OUT_DIR / "summary.json"
COMPARISON_CSV = OUT_DIR / "ncses_our_comparison_cells.csv"
CROSSWALK_CSV = OUT_DIR / "ncses_institution_crosswalk.csv"
OUR_AGG_CSV = OUT_DIR / "our_university_field_year_counts.csv"
NCSES_AGG_CSV = OUT_DIR / "ncses_university_field_year_counts.csv"
DOC_PATH = common.DOCS_DIR / "ncses_comparison.html"
NSF_CROSSWALK = common.CODEX_DATA / "goid_user_id_nsf.csv"
EXCLUDED_BROAD_FIELDS = {"humanities and arts"}
NCSES_TO_CARNEGIE_ALIASES = {
    "city hope irell and manella graduate school biological sciences": "irell and manella graduate school biological sciences city hope",
    "cornell university weill cornell medical college": "weill medical college cornell university",
    "cuny graduate center": "cuny graduate school and university center",
    "florida a and m university": "florida agricultural and mechanical university",
    "mayo clinic mayo graduate school": "mayo clinic college medicine and science",
    "north carolina agricultural and technical state university": "north carolina a and t state university",
    "prairie view a and m university": "prairie view a and m university",
    "rutgers state university new jersey new brunswick": "rutgers university new brunswick",
    "rutgers state university new jersey newark": "rutgers university newark",
    "rutgers state university new jersey camden": "rutgers university camden",
}


def latest_ncses_zip() -> Path:
    candidates = sorted(common.ROOT.glob("ncses_table_srv_data_SED_*.zip"))
    if not candidates:
        raise FileNotFoundError("No ncses_table_srv_data_SED_*.zip file found.")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_ncses_rows(zip_path: Path) -> list[Dict[str, str]]:
    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [name for name in zf.namelist() if name.endswith(".csv")]
        if not csv_names:
            raise FileNotFoundError(f"{zip_path.name} does not contain a CSV file.")
        with zf.open(csv_names[0]) as bf:
            text = io.TextIOWrapper(bf, encoding="utf-8-sig", newline="")
            return list(csv.DictReader(text))


def load_carniege_nsf_map() -> tuple[dict[tuple[str, str], Dict[str, str]], Counter]:
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
        if len(values) > 1:
            diagnostics["crosswalk_pairs_with_multiple_unitids_same_fields"] += 1
        diagnostics["crosswalk_safe_pairs"] += 1
    return out, diagnostics


def build_carnegie_index() -> tuple[
    dict[str, Dict[str, str]],
    dict[tuple[str, int], int],
    dict[tuple[str, int, str], int],
    dict[tuple[str, int, str], int],
    Counter,
]:
    users = common.load_first_job_users()
    carnegie_map, diagnostics = load_carniege_nsf_map()
    user_phd_rows: dict[str, Dict[str, str]] = {}
    all_counts: dict[tuple[str, int], int] = defaultdict(int)
    broad_counts: dict[tuple[str, int, str], int] = defaultdict(int)
    major_counts: dict[tuple[str, int, str], int] = defaultdict(int)

    for user_id, info in users.items():
        year = common.to_int(info.get("grad_year"))
        if year is None:
            diagnostics["missing_grad_year"] += 1
            continue
        goid = info.get("goid", "")
        carnegie = carnegie_map.get((goid, user_id))
        if carnegie is None:
            diagnostics["missing_carnegie_crosswalk_row"] += 1
            continue
        inst = carnegie.get("carnegie_name", "")
        if not inst:
            diagnostics["missing_carnegie_name"] += 1
            continue
        inst_norm = common.norm_institution(inst)
        if not inst_norm:
            diagnostics["missing_carnegie_name"] += 1
            continue
        nsf_broad = carnegie.get("nsf_broad", "") or info.get("nsf_broad", "")
        nsf_major = carnegie.get("nsf_major", "") or info.get("nsf_major", "")
        if common.norm_label(nsf_broad) in EXCLUDED_BROAD_FIELDS:
            diagnostics["excluded_humanities_and_arts_users"] += 1
            continue
        user_phd_rows[user_id] = {
            "rev_user_id": user_id,
            "goid": goid,
            "grad_year": str(year),
            "phd_institution": inst,
            "phd_institution_norm": inst_norm,
            "phd_country": "United States",
            "phd_selection_source": "goid_user_id_nsf_carnegie",
            "carnegie_unitid": carnegie.get("carnegie_unitid", ""),
            "nsf_broad": nsf_broad,
            "nsf_major": nsf_major,
        }
        all_counts[(inst_norm, year)] += 1
        if nsf_broad:
            broad_counts[(inst_norm, year, common.norm_label(nsf_broad))] += 1
        if nsf_major:
            major_counts[(inst_norm, year, common.norm_label(nsf_major))] += 1
        diagnostics["matched_carnegie_crosswalk_row"] += 1
    return user_phd_rows, all_counts, broad_counts, major_counts, diagnostics


def build_ncses_counts(rows: list[Dict[str, str]]) -> tuple[
    dict[tuple[str, int], int],
    dict[tuple[str, int, str], int],
    dict[tuple[str, int, str], int],
    dict[str, str],
    dict[str, str],
]:
    all_counts: dict[tuple[str, int], int] = defaultdict(int)
    broad_counts: dict[tuple[str, int, str], int] = defaultdict(int)
    major_counts: dict[tuple[str, int, str], int] = defaultdict(int)
    inst_display: dict[str, str] = {}
    broad_display: dict[str, str] = {}
    for row in rows:
        inst = common.clean(row.get("Institution Name"))
        year = common.to_int(row.get("Year"))
        count = common.to_int(row.get("Doctorate Recipients by Institution")) or 0
        broad = common.clean(row.get("Trend Broad Fields"))
        major = common.clean(row.get("Trend Major Fields"))
        if not inst or year is None:
            continue
        if common.norm_label(broad) in EXCLUDED_BROAD_FIELDS:
            continue
        inst_norm = common.norm_institution(inst)
        inst_display.setdefault(inst_norm, inst)
        all_counts[(inst_norm, year)] += count
        if broad:
            broad_norm = common.norm_label(broad)
            broad_display.setdefault(broad_norm, broad)
            broad_counts[(inst_norm, year, broad_norm)] += count
        if major:
            major_counts[(inst_norm, year, common.norm_label(major))] += count
    return all_counts, broad_counts, major_counts, inst_display, broad_display


def ncses_institution_variants(name: str) -> list[str]:
    variants = set(common.institution_variants(name))
    if "," in name:
        parts = [part.strip() for part in name.split(",") if part.strip()]
        remainder = " ".join(parts[1:]).lower() if len(parts) > 1 else ""
        first = parts[0]
        subunit_terms = (
            "center",
            "centre",
            "health",
            "medical",
            "medicine",
            "school",
            "college",
            "institute",
            "campus",
            "engineering",
        )
        if not any(term in remainder for term in subunit_terms):
            variants.update(common.institution_variants(first))
        if len(parts) >= 2:
            if parts[0].lower() in {"suny", "cuny"}:
                variants.update(common.institution_variants(parts[1]))
            if parts[0].lower().startswith("u. ") and not any(
                term in remainder for term in subunit_terms
            ):
                variants.update(common.institution_variants(parts[0]))
    return sorted([variant for variant in variants if variant], key=lambda item: (-len(item), item))


def unique_prefix_match(variant: str, our_norms: list[str]) -> str:
    if len(variant) < 12:
        return ""
    matches = [
        norm
        for norm in our_norms
        if norm.startswith(variant + " ") or variant.startswith(norm + " ")
    ]
    matches = sorted(set(matches))
    return matches[0] if len(matches) == 1 else ""


def has_subunit_signal(name: str) -> bool:
    text = name.lower()
    return any(
        term in text
        for term in [
            "center for",
            "health science",
            "medical college",
            "graduate school",
            "school of",
            "campus",
            "institute of",
            "college of",
        ]
    )


def build_crosswalk(
    ncses_inst_display: dict[str, str],
    our_counts: dict[tuple[str, int], int],
    user_phd_rows: dict[str, Dict[str, str]],
) -> dict[str, Dict[str, object]]:
    our_norm_counts: Counter = Counter()
    our_display: dict[str, str] = {}
    our_unitids: dict[str, set[str]] = defaultdict(set)
    for row in user_phd_rows.values():
        norm = row["phd_institution_norm"]
        our_norm_counts[norm] += 1
        our_display.setdefault(norm, row["phd_institution"])
        if row.get("carnegie_unitid"):
            our_unitids[norm].update(str(row["carnegie_unitid"]).split("|"))

    our_norms = list(our_norm_counts)
    crosswalk: dict[str, Dict[str, object]] = {}
    for ncses_norm, ncses_name in ncses_inst_display.items():
        match = ""
        method = "unmatched"
        score = 0.0
        alias = NCSES_TO_CARNEGIE_ALIASES.get(ncses_norm, "")
        if alias and alias in our_norm_counts:
            match = alias
            method = "manual_alias"
            score = 1.0
        variants = ncses_institution_variants(ncses_name)
        if not match:
            for variant in variants:
                if variant in our_norm_counts:
                    match = variant
                    method = "normalized_exact_or_variant"
                    score = 1.0
                    break
        if not match and not has_subunit_signal(ncses_name):
            for variant in variants:
                prefix = unique_prefix_match(variant, our_norms)
                if prefix:
                    match = prefix
                    method = "unique_prefix_variant"
                    score = round(difflib.SequenceMatcher(None, variant, prefix).ratio(), 4)
                    break
        if not match and our_norms:
            best = difflib.get_close_matches(ncses_norm, our_norms, n=1, cutoff=0.965)
            if best:
                match = best[0]
                method = "fuzzy_0.965"
                score = round(difflib.SequenceMatcher(None, ncses_norm, match).ratio(), 4)
        crosswalk[ncses_norm] = {
            "ncses_institution": ncses_name,
            "ncses_institution_norm": ncses_norm,
            "our_institution_norm": match,
            "our_institution": our_display.get(match, ""),
            "our_carnegie_unitid": "|".join(sorted(our_unitids.get(match, set()))),
            "match_method": method,
            "match_score": score,
            "our_user_count": our_norm_counts.get(match, 0),
        }
    return crosswalk


def remap_ncses_counts(
    counts: dict[tuple, int],
    crosswalk: dict[str, Dict[str, object]],
    allowed_years: set[int] | None = None,
) -> dict[tuple, int]:
    out: dict[tuple, int] = defaultdict(int)
    for key, count in counts.items():
        if allowed_years is not None and int(key[1]) not in allowed_years:
            continue
        inst_norm = key[0]
        matched = str(crosswalk.get(inst_norm, {}).get("our_institution_norm") or "")
        if not matched:
            continue
        out[(matched, *key[1:])] += count
    return out


def compare_counts(
    level: str,
    ncses_counts: dict[tuple, int],
    our_counts: dict[tuple, int],
    inst_names: dict[str, str],
    field_names: dict[str, str] | None = None,
) -> list[Dict[str, object]]:
    rows: list[Dict[str, object]] = []
    for key, ncses_count in ncses_counts.items():
        our_count = our_counts.get(key, 0)
        inst_norm = str(key[0])
        year = int(key[1])
        field_norm = str(key[2]) if len(key) > 2 else "All fields"
        rows.append(
            {
                "level": level,
                "institution": inst_names.get(inst_norm, inst_norm),
                "institution_norm": inst_norm,
                "year": year,
                "field": (field_names or {}).get(field_norm, field_norm),
                "field_norm": field_norm,
                "ncses_count": ncses_count,
                "our_count": our_count,
                "difference": our_count - ncses_count,
                "coverage": round(our_count / ncses_count, 4) if ncses_count else "",
            }
        )
    return rows


def aggregate_for_page(rows: list[Dict[str, object]]) -> dict[str, object]:
    overall_year: dict[int, Counter] = defaultdict(Counter)
    broad_year: dict[str, dict[int, Counter]] = defaultdict(lambda: defaultdict(Counter))
    inst_total: Counter = Counter()
    field_total: Counter = Counter()

    for row in rows:
        ncses = int(row["ncses_count"])
        ours = int(row["our_count"])
        year = int(row["year"])
        level = str(row["level"])
        field = str(row["field"])
        inst = str(row["institution"])
        if level == "all":
            overall_year[year]["ncses"] += ncses
            overall_year[year]["ours"] += ours
            inst_total[(inst, "ncses")] += ncses
            inst_total[(inst, "ours")] += ours
        elif level == "broad":
            broad_year[field][year]["ncses"] += ncses
            broad_year[field][year]["ours"] += ours
            field_total[(field, "ncses")] += ncses
            field_total[(field, "ours")] += ours

    years_payload = [
        {
            "year": year,
            "ncses": counts["ncses"],
            "ours": counts["ours"],
            "coverage": round(counts["ours"] / counts["ncses"], 4) if counts["ncses"] else 0,
        }
        for year, counts in sorted(overall_year.items())
    ]
    broad_payload = []
    for field, by_year in sorted(broad_year.items()):
        broad_payload.append(
            {
                "field": field,
                "years": [
                    {
                        "year": year,
                        "ncses": counts["ncses"],
                        "ours": counts["ours"],
                        "coverage": round(counts["ours"] / counts["ncses"], 4)
                        if counts["ncses"]
                        else 0,
                    }
                    for year, counts in sorted(by_year.items())
                ],
            }
        )

    inst_rows = []
    for inst in sorted({key[0] for key in inst_total}):
        ncses = inst_total[(inst, "ncses")]
        ours = inst_total[(inst, "ours")]
        inst_rows.append(
            {
                "institution": inst,
                "ncses": ncses,
                "ours": ours,
                "difference": ours - ncses,
                "coverage": round(ours / ncses, 4) if ncses else 0,
            }
        )
    inst_rows.sort(key=lambda r: abs(int(r["difference"])), reverse=True)

    field_rows = []
    for field in sorted({key[0] for key in field_total}):
        ncses = field_total[(field, "ncses")]
        ours = field_total[(field, "ours")]
        field_rows.append(
            {
                "field": field,
                "ncses": ncses,
                "ours": ours,
                "difference": ours - ncses,
                "coverage": round(ours / ncses, 4) if ncses else 0,
            }
        )
    field_rows.sort(key=lambda r: r["ncses"], reverse=True)

    return {
        "overall_year": years_payload,
        "broad_year": broad_payload,
        "institution_gaps": inst_rows[:100],
        "field_summary": field_rows,
    }


def write_page(payload: dict[str, object]) -> None:
    data_json = json.dumps(payload)
    body = """
    <div class="card"><div id="stats" class="stats"></div></div>
    <div class="card">
      <div class="controls">
        <div class="control">
          <label for="series-select">Series</label>
          <select id="series-select"></select>
        </div>
      </div>
      <canvas id="coverage-chart" class="chart"></canvas>
      <div class="note">Our institution and field counts use the Carnegie institution and NSF fields from codex_data/goid_user_id_nsf.csv. Humanities and arts is excluded. Counts are summed over matched NCSES institutions. Field comparisons use exact normalized NCSES/NSF labels; ambiguous taxonomy cells are left out rather than forced.</div>
    </div>
    <div class="card">
      <h2>Field Summary</h2>
      <div id="field-table"></div>
    </div>
    <div class="card">
      <h2>Largest University Gaps</h2>
      <div id="gap-table"></div>
    </div>
    """
    script = f"""
  <script>
    const DATA = {data_json};
    function fmt(n) {{ return Number(n).toLocaleString(); }}
    function pct(x) {{ return (Number(x) * 100).toFixed(1) + '%'; }}
    function table(headers, rows) {{
      return '<table><thead><tr>' + headers.map(h => `<th>${{h}}</th>`).join('') + '</tr></thead><tbody>' +
        rows.map(r => '<tr>' + r.map(c => `<td>${{c}}</td>`).join('') + '</tr>').join('') + '</tbody></table>';
    }}
    function draw(canvas, rows, title) {{
      const ctx = canvas.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth || 1100, h = canvas.clientHeight || 460;
      canvas.width = w * dpr; canvas.height = h * dpr; ctx.setTransform(dpr,0,0,dpr,0,0);
      ctx.clearRect(0,0,w,h);
      const margin = {{left:70,right:140,top:24,bottom:48}};
      const years = rows.map(r => r.year);
      const maxVal = Math.max(...rows.flatMap(r => [r.ncses, r.ours]), 1);
      const x = y => margin.left + (years.length <= 1 ? 0 : (y - years[0]) / (years[years.length-1] - years[0]) * (w-margin.left-margin.right));
      const y = v => h - margin.bottom - v / maxVal * (h-margin.top-margin.bottom);
      ctx.strokeStyle = '#ddd7ca'; ctx.fillStyle = '#666'; ctx.font = '12px Georgia';
      for (let i=0;i<=4;i++) {{
        const val = maxVal * i / 4, yy = y(val);
        ctx.beginPath(); ctx.moveTo(margin.left, yy); ctx.lineTo(w-margin.right, yy); ctx.stroke();
        ctx.fillText(fmt(Math.round(val)), 8, yy+4);
      }}
      function line(key, color, label) {{
        ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.beginPath();
        rows.forEach((r,i) => {{ const xx=x(r.year), yy=y(r[key]); if(i) ctx.lineTo(xx,yy); else ctx.moveTo(xx,yy); }});
        ctx.stroke();
        ctx.fillStyle = color;
        rows.forEach(r => {{ ctx.beginPath(); ctx.arc(x(r.year), y(r[key]), 2.5, 0, Math.PI*2); ctx.fill(); }});
        ctx.fillText(label, w-margin.right+18, y(rows[rows.length-1][key])+4);
      }}
      line('ncses', '#c43c39', 'NCSES');
      line('ours', '#1f4e79', 'Our data');
      ctx.fillStyle = '#222'; ctx.font = '16px Georgia'; ctx.fillText(title, margin.left, 18);
      ctx.fillStyle = '#666'; ctx.font = '12px Georgia';
      const ticks = years.filter((_, i) => i % Math.max(1, Math.ceil(years.length/8)) === 0);
      ticks.forEach(yr => ctx.fillText(yr, x(yr)-12, h-18));
    }}
    function init() {{
      const s = DATA.summary;
      document.getElementById('stats').innerHTML = [
        ['Matched PhD users', fmt(s.our_phd_users_matched)],
        ['NCSES institutions', fmt(s.ncses_institutions)],
        ['Institution matches', fmt(s.matched_ncses_institutions)],
        ['Unmatched NCSES institutions', fmt(s.unmatched_ncses_institutions)],
        ['Comparison years', s.comparison_year_min + '-' + s.comparison_year_max]
      ].map(([label,value]) => `<div class="stat"><div class="value">${{value}}</div><div class="label">${{label}}</div></div>`).join('');
      const select = document.getElementById('series-select');
      select.innerHTML = '<option value="overall">All matched institutions</option>' + DATA.page.broad_year.map((d,i) => `<option value="${{i}}">${{d.field}}</option>`).join('');
      function render() {{
        const val = select.value;
        const rows = val === 'overall' ? DATA.page.overall_year : DATA.page.broad_year[Number(val)].years;
        const title = val === 'overall' ? 'All fields' : DATA.page.broad_year[Number(val)].field;
        draw(document.getElementById('coverage-chart'), rows, title);
      }}
      select.addEventListener('change', render); render();
      document.getElementById('field-table').innerHTML = table(['Field','NCSES','Our data','Coverage','Difference'], DATA.page.field_summary.map(r => [r.field, fmt(r.ncses), fmt(r.ours), pct(r.coverage), fmt(r.difference)]));
      document.getElementById('gap-table').innerHTML = table(['Institution','NCSES','Our data','Coverage','Difference'], DATA.page.institution_gaps.slice(0,50).map(r => [r.institution, fmt(r.ncses), fmt(r.ours), pct(r.coverage), fmt(r.difference)]));
    }}
    init();
  </script>
"""
    html = common.html_shell(
        "NCSES vs Our PhD Counts",
        "University-field-year doctorate counts from NCSES compared with the matched PhD dataset.",
        body,
        script,
    )
    common.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(html, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = latest_ncses_zip()
    ncses_rows = read_ncses_rows(zip_path)
    user_phd_rows, our_all, our_broad, our_major, diagnostics = build_carnegie_index()
    ncses_all_raw, ncses_broad_raw, ncses_major_raw, ncses_inst_display, broad_display = build_ncses_counts(ncses_rows)
    crosswalk = build_crosswalk(ncses_inst_display, our_all, user_phd_rows)
    overlap_years = {int(key[1]) for key in our_all}
    ncses_all = remap_ncses_counts(ncses_all_raw, crosswalk, overlap_years)
    ncses_broad = remap_ncses_counts(ncses_broad_raw, crosswalk, overlap_years)
    ncses_major = remap_ncses_counts(ncses_major_raw, crosswalk, overlap_years)

    inst_names = {row["phd_institution_norm"]: row["phd_institution"] for row in user_phd_rows.values()}
    comparison_rows = compare_counts("all", ncses_all, our_all, inst_names)
    comparison_rows.extend(compare_counts("broad", ncses_broad, our_broad, inst_names, broad_display))

    common.write_csv(CROSSWALK_CSV, [
        "ncses_institution",
        "ncses_institution_norm",
        "our_institution",
        "our_institution_norm",
        "our_carnegie_unitid",
        "match_method",
        "match_score",
        "our_user_count",
    ], crosswalk.values())
    common.write_csv(COMPARISON_CSV, [
        "level",
        "institution",
        "institution_norm",
        "year",
        "field",
        "field_norm",
        "ncses_count",
        "our_count",
        "difference",
        "coverage",
    ], comparison_rows)

    our_rows = [
        {"level": "all", "institution_norm": k[0], "year": k[1], "field_norm": "All fields", "count": v}
        for k, v in our_all.items()
    ]
    our_rows.extend(
        {"level": "broad", "institution_norm": k[0], "year": k[1], "field_norm": k[2], "count": v}
        for k, v in our_broad.items()
    )
    common.write_csv(OUR_AGG_CSV, ["level", "institution_norm", "year", "field_norm", "count"], our_rows)
    ncses_rows_out = [
        {"level": "all", "institution_norm": k[0], "year": k[1], "field_norm": "All fields", "count": v}
        for k, v in ncses_all.items()
    ]
    ncses_rows_out.extend(
        {"level": "broad", "institution_norm": k[0], "year": k[1], "field_norm": k[2], "count": v}
        for k, v in ncses_broad.items()
    )
    common.write_csv(NCSES_AGG_CSV, ["level", "institution_norm", "year", "field_norm", "count"], ncses_rows_out)

    matched_institutions = sum(1 for row in crosswalk.values() if row["our_institution_norm"])
    summary = {
        "source_zip": str(zip_path),
        "ncses_rows": len(ncses_rows),
        "ncses_institutions": len(ncses_inst_display),
        "matched_ncses_institutions": matched_institutions,
        "unmatched_ncses_institutions": len(ncses_inst_display) - matched_institutions,
        "our_phd_users_matched": diagnostics["matched_carnegie_crosswalk_row"],
        "our_phd_users_missing_degree_row": diagnostics["missing_carnegie_crosswalk_row"],
        "institution_source": "codex_data/goid_user_id_nsf.csv carnegie_name/carnegie_unitid",
        "crosswalk_safe_pairs": diagnostics["crosswalk_safe_pairs"],
        "crosswalk_ambiguous_pairs": diagnostics["crosswalk_ambiguous_pairs"],
        "crosswalk_pairs_with_multiple_unitids_same_fields": diagnostics[
            "crosswalk_pairs_with_multiple_unitids_same_fields"
        ],
        "excluded_broad_fields": sorted(EXCLUDED_BROAD_FIELDS),
        "excluded_humanities_and_arts_users": diagnostics["excluded_humanities_and_arts_users"],
        "comparison_year_min": min(overlap_years) if overlap_years else None,
        "comparison_year_max": max(overlap_years) if overlap_years else None,
        "comparison_cells": len(comparison_rows),
    }
    payload = {"summary": summary, "page": aggregate_for_page(comparison_rows)}
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_page(payload)
    print(f"Wrote {DOC_PATH}")
    print(f"Matched NCSES institutions: {matched_institutions}/{len(ncses_inst_display)}")
    print(f"Our users with Carnegie institution row: {diagnostics['matched_carnegie_crosswalk_row']:,}")


if __name__ == "__main__":
    main()
