#!/usr/bin/env python3
"""Build the NCSES / ProQuest / matched-ProQuest coverage page."""

from __future__ import annotations

import csv
import difflib
import io
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable

import dashboard_data_common as common


OUT_DIR = common.OUTPUT_DIR / "ncses_comparison"
SUMMARY_JSON = OUT_DIR / "summary.json"
COMPARISON_CSV = OUT_DIR / "ncses_proquest_matched_cells.csv"
CROSSWALK_CSV = OUT_DIR / "ncses_institution_crosswalk.csv"
OUR_AGG_CSV = OUT_DIR / "matched_proquest_university_field_year_counts.csv"
NCSES_AGG_CSV = OUT_DIR / "ncses_university_field_year_counts.csv"
PQ_AGG_CSV = OUT_DIR / "proquest_university_field_year_counts.csv"
DOC_PATH = common.DOCS_DIR / "ncses_comparison.html"
NSF_CROSSWALK = common.CODEX_DATA / "goid_user_id_nsf.csv"
PQ_CSV = common.ROOT / "pq.csv"
YEAR_MIN = 1980
YEAR_MAX = 2019

EXCLUDED_BROAD_FIELDS = {
    "",
    "business",
    "education",
    "humanities",
    "humanities and arts",
    "other non science and engineering",
    "psychology",
    "social sciences",
    "visual and performing arts",
}

FIELD_ALIASES = {
    "Multidisciplinary/ interdisciplinary sciences": "Multidisciplinary sciences",
}

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


def in_year_window(year: int | None) -> bool:
    return year is not None and YEAR_MIN <= year <= YEAR_MAX


def field_label(value: object) -> str:
    label = common.clean(value)
    return FIELD_ALIASES.get(label, label)


def field_norm(value: object) -> str:
    return common.norm_label(field_label(value))


def include_broad(value: object) -> bool:
    return common.norm_label(field_label(value)) not in EXCLUDED_BROAD_FIELDS


def proquest_count_id(row: Dict[str, str]) -> str:
    return common.clean(row.get("pq_goid_row")) or common.norm_id(row.get("goid"))


def pct(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0


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
                    field_label(row.get("nsf_primary")),
                    field_label(row.get("nsf_major")),
                    field_label(row.get("nsf_broad")),
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


def empty_tables() -> dict[str, object]:
    return {
        "all": defaultdict(set),
        "broad": defaultdict(set),
        "major": defaultdict(set),
        "inst_display": {},
        "unitids": defaultdict(set),
        "broad_display": {},
        "major_display": {},
    }


def finalize_set_counts(table: dict[tuple, set[str]]) -> dict[tuple, int]:
    return {key: len(ids) for key, ids in table.items()}


def build_proquest_counts() -> tuple[dict[str, object], Counter]:
    tables = empty_tables()
    diagnostics: Counter = Counter()
    if not PQ_CSV.exists():
        raise FileNotFoundError(f"Missing {PQ_CSV}")

    with PQ_CSV.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            diagnostics["pq_rows"] += 1
            year = common.to_int(row.get("graduation_year"))
            if not in_year_window(year):
                diagnostics["pq_excluded_year"] += 1
                continue
            broad = field_label(row.get("nsf_broad"))
            if not include_broad(broad):
                diagnostics["pq_excluded_field"] += 1
                continue
            inst = common.clean(row.get("carnegie_name"))
            inst_norm = common.norm_institution(inst)
            identifier = proquest_count_id(row)
            if not inst_norm or not identifier:
                diagnostics["pq_missing_institution_or_id"] += 1
                continue
            major = field_label(row.get("nsf_major"))
            tables["inst_display"].setdefault(inst_norm, inst)
            if row.get("carnegie_unitid"):
                tables["unitids"][inst_norm].add(common.norm_id(row.get("carnegie_unitid")))
            tables["all"][(inst_norm, year)].add(identifier)
            if broad:
                broad_norm = field_norm(broad)
                tables["broad_display"].setdefault(broad_norm, broad)
                tables["broad"][(inst_norm, year, broad_norm)].add(identifier)
            if major:
                major_norm = field_norm(major)
                tables["major_display"].setdefault(major_norm, major)
                tables["major"][(inst_norm, year, major_norm)].add(identifier)
            diagnostics["pq_included_rows"] += 1

    return {
        "all": finalize_set_counts(tables["all"]),
        "broad": finalize_set_counts(tables["broad"]),
        "major": finalize_set_counts(tables["major"]),
        "inst_display": dict(tables["inst_display"]),
        "unitids": {key: set(value) for key, value in tables["unitids"].items()},
        "broad_display": dict(tables["broad_display"]),
        "major_display": dict(tables["major_display"]),
    }, diagnostics


def build_matched_counts() -> tuple[dict[str, object], Counter]:
    users = common.load_first_job_users()
    carnegie_map, diagnostics = load_carnegie_nsf_map()
    tables = empty_tables()

    for user_id, info in users.items():
        year = common.to_int(info.get("grad_year"))
        if not in_year_window(year):
            diagnostics["matched_excluded_year"] += 1
            continue
        carnegie = carnegie_map.get((info.get("goid", ""), user_id))
        if carnegie is None:
            diagnostics["matched_missing_carnegie_crosswalk_row"] += 1
            continue
        broad = carnegie.get("nsf_broad", "") or field_label(info.get("nsf_broad"))
        if not include_broad(broad):
            diagnostics["matched_excluded_field"] += 1
            continue
        inst = carnegie.get("carnegie_name", "")
        inst_norm = common.norm_institution(inst)
        identifier = info.get("goid") or user_id
        if not inst_norm or not identifier:
            diagnostics["matched_missing_institution_or_id"] += 1
            continue
        major = carnegie.get("nsf_major", "") or field_label(info.get("nsf_major"))
        tables["inst_display"].setdefault(inst_norm, inst)
        if carnegie.get("carnegie_unitid"):
            tables["unitids"][inst_norm].update(str(carnegie["carnegie_unitid"]).split("|"))
        tables["all"][(inst_norm, year)].add(identifier)
        if broad:
            broad_norm = field_norm(broad)
            tables["broad_display"].setdefault(broad_norm, broad)
            tables["broad"][(inst_norm, year, broad_norm)].add(identifier)
        if major:
            major_norm = field_norm(major)
            tables["major_display"].setdefault(major_norm, major)
            tables["major"][(inst_norm, year, major_norm)].add(identifier)
        diagnostics["matched_included_rows"] += 1

    return {
        "all": finalize_set_counts(tables["all"]),
        "broad": finalize_set_counts(tables["broad"]),
        "major": finalize_set_counts(tables["major"]),
        "inst_display": dict(tables["inst_display"]),
        "unitids": {key: set(value) for key, value in tables["unitids"].items()},
        "broad_display": dict(tables["broad_display"]),
        "major_display": dict(tables["major_display"]),
    }, diagnostics


def build_ncses_counts(rows: list[Dict[str, str]]) -> tuple[dict[str, object], Counter]:
    tables = {
        "all": defaultdict(int),
        "broad": defaultdict(int),
        "major": defaultdict(int),
        "inst_display": {},
        "broad_display": {},
        "major_display": {},
    }
    diagnostics: Counter = Counter()
    for row in rows:
        diagnostics["ncses_rows"] += 1
        inst = common.clean(row.get("Institution Name"))
        year = common.to_int(row.get("Year"))
        count = common.to_int(row.get("Doctorate Recipients by Institution")) or 0
        broad = field_label(row.get("Trend Broad Fields"))
        major = field_label(row.get("Trend Major Fields"))
        if not inst or not in_year_window(year):
            diagnostics["ncses_excluded_year_or_institution"] += 1
            continue
        if not include_broad(broad):
            diagnostics["ncses_excluded_field"] += 1
            continue
        inst_norm = common.norm_institution(inst)
        broad_norm = field_norm(broad)
        major_norm = field_norm(major)
        tables["inst_display"].setdefault(inst_norm, inst)
        tables["all"][(inst_norm, year)] += count
        if broad:
            tables["broad_display"].setdefault(broad_norm, broad)
            tables["broad"][(inst_norm, year, broad_norm)] += count
        if major:
            tables["major_display"].setdefault(major_norm, major)
            tables["major"][(inst_norm, year, major_norm)] += count
        diagnostics["ncses_included_rows"] += 1

    return {key: dict(value) for key, value in tables.items()}, diagnostics


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
            if parts[0].lower().startswith("u. ") and not any(term in remainder for term in subunit_terms):
                variants.update(common.institution_variants(parts[0]))
    return sorted([variant for variant in variants if variant], key=lambda item: (-len(item), item))


def unique_prefix_match(variant: str, candidate_norms: list[str]) -> str:
    if len(variant) < 12:
        return ""
    matches = [
        norm
        for norm in candidate_norms
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


def build_candidate_institutions(*tables: dict[str, object]) -> tuple[Counter, dict[str, str], dict[str, set[str]]]:
    counts: Counter = Counter()
    display: dict[str, str] = {}
    unitids: dict[str, set[str]] = defaultdict(set)
    for table in tables:
        inst_display = table["inst_display"]
        for norm, name in inst_display.items():
            display.setdefault(norm, name)
        for key, count in table["all"].items():
            counts[key[0]] += count
        for norm, values in table.get("unitids", {}).items():
            unitids[norm].update(str(v) for v in values if v)
    return counts, display, unitids


def build_crosswalk(
    ncses_inst_display: dict[str, str],
    candidate_counts: Counter,
    candidate_display: dict[str, str],
    candidate_unitids: dict[str, set[str]],
) -> dict[str, Dict[str, object]]:
    candidate_norms = list(candidate_counts)
    crosswalk: dict[str, Dict[str, object]] = {}
    for ncses_norm, ncses_name in ncses_inst_display.items():
        match = ""
        method = "unmatched"
        score = 0.0
        alias = NCSES_TO_CARNEGIE_ALIASES.get(ncses_norm, "")
        if alias and alias in candidate_counts:
            match = alias
            method = "manual_alias"
            score = 1.0
        variants = ncses_institution_variants(ncses_name)
        if not match:
            for variant in variants:
                if variant in candidate_counts:
                    match = variant
                    method = "normalized_exact_or_variant"
                    score = 1.0
                    break
        if not match and not has_subunit_signal(ncses_name):
            for variant in variants:
                prefix = unique_prefix_match(variant, candidate_norms)
                if prefix:
                    match = prefix
                    method = "unique_prefix_variant"
                    score = round(difflib.SequenceMatcher(None, variant, prefix).ratio(), 4)
                    break
        if not match and candidate_norms:
            best = difflib.get_close_matches(ncses_norm, candidate_norms, n=1, cutoff=0.965)
            if best:
                match = best[0]
                method = "fuzzy_0.965"
                score = round(difflib.SequenceMatcher(None, ncses_norm, match).ratio(), 4)
        crosswalk[ncses_norm] = {
            "ncses_institution": ncses_name,
            "ncses_institution_norm": ncses_norm,
            "carnegie_institution": candidate_display.get(match, ""),
            "carnegie_institution_norm": match,
            "carnegie_unitid": "|".join(sorted(candidate_unitids.get(match, set()))),
            "match_method": method,
            "match_score": score,
            "candidate_record_count": candidate_counts.get(match, 0),
        }
    return crosswalk


def remap_ncses_counts(counts: dict[tuple, int], crosswalk: dict[str, Dict[str, object]]) -> dict[tuple, int]:
    out: dict[tuple, int] = defaultdict(int)
    for key, count in counts.items():
        inst_norm = key[0]
        matched = str(crosswalk.get(inst_norm, {}).get("carnegie_institution_norm") or "")
        if not matched:
            continue
        out[(matched, *key[1:])] += count
    return dict(out)


def sum_by_year(counts: dict[tuple, int]) -> dict[int, int]:
    out: dict[int, int] = defaultdict(int)
    for key, count in counts.items():
        out[int(key[1])] += count
    return dict(out)


def sum_by_field_year(counts: dict[tuple, int]) -> dict[str, dict[int, int]]:
    out: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for key, count in counts.items():
        if len(key) < 3:
            continue
        out[str(key[2])][int(key[1])] += count
    return {field: dict(years) for field, years in out.items()}


def years_payload(ncses: dict[int, int], pq: dict[int, int], matched: dict[int, int]) -> list[dict[str, int]]:
    years = sorted(set(ncses) | set(pq) | set(matched))
    return [
        {
            "year": year,
            "ncses": ncses.get(year, 0),
            "proquest": pq.get(year, 0),
            "matched": matched.get(year, 0),
        }
        for year in years
    ]


def group_payload(
    ncses_counts: dict[tuple, int],
    pq_counts: dict[tuple, int],
    matched_counts: dict[tuple, int],
    field_display: dict[str, str] | None = None,
    field_key: str = "All fields",
) -> list[dict[str, object]]:
    fields = sorted({key[2] for key in ncses_counts if len(key) > 2} | {key[2] for key in pq_counts if len(key) > 2} | {key[2] for key in matched_counts if len(key) > 2})
    if not fields:
        fields = [field_key]
    out = []
    for field in fields:
        n = defaultdict(int)
        p = defaultdict(int)
        m = defaultdict(int)
        if field == field_key:
            for key, count in ncses_counts.items():
                n[int(key[1])] += count
            for key, count in pq_counts.items():
                p[int(key[1])] += count
            for key, count in matched_counts.items():
                m[int(key[1])] += count
        else:
            for key, count in ncses_counts.items():
                if len(key) > 2 and key[2] == field:
                    n[int(key[1])] += count
            for key, count in pq_counts.items():
                if len(key) > 2 and key[2] == field:
                    p[int(key[1])] += count
            for key, count in matched_counts.items():
                if len(key) > 2 and key[2] == field:
                    m[int(key[1])] += count
        total_n = sum(n.values())
        total_p = sum(p.values())
        total_m = sum(m.values())
        if total_n + total_p + total_m <= 0:
            continue
        out.append(
            {
                "field": (field_display or {}).get(field, field),
                "field_norm": field,
                "ncses": total_n,
                "proquest": total_p,
                "matched": total_m,
                "pq_ncses_coverage": pct(total_p, total_n),
                "matched_ncses_coverage": pct(total_m, total_n),
                "matched_pq_coverage": pct(total_m, total_p),
                "years": years_payload(n, p, m),
            }
        )
    out.sort(key=lambda row: (-int(row["ncses"]), str(row["field"])))
    return out


def filter_counts_for_institution(counts: dict[tuple, int], inst_norm: str) -> dict[tuple, int]:
    return {key: count for key, count in counts.items() if key[0] == inst_norm}


def build_page_payload(
    ncses: dict[str, object],
    ncses_remapped: dict[str, dict[tuple, int]],
    pq: dict[str, object],
    matched: dict[str, object],
    crosswalk: dict[str, Dict[str, object]],
) -> dict[str, object]:
    broad_display = {**ncses["broad_display"], **pq["broad_display"], **matched["broad_display"]}
    major_display = {**ncses["major_display"], **pq["major_display"], **matched["major_display"]}
    candidate_counts, candidate_display, _unitids = build_candidate_institutions(pq, matched)

    national = {
        "name": "All US institutions",
        "carnegie_unitid": "",
        "views": {
            "overall": group_payload(ncses["all"], pq["all"], matched["all"]),
            "broad": group_payload(ncses["broad"], pq["broad"], matched["broad"], broad_display),
            "major": group_payload(ncses["major"], pq["major"], matched["major"], major_display),
        },
    }

    institution_rows = []
    institution_payload = []
    institution_norms = sorted(set(ncses_remapped["all"]) | set(pq["all"]) | set(matched["all"]))
    institution_norms = sorted({key[0] for key in institution_norms} | set(candidate_counts))
    for inst_norm in institution_norms:
        n_all = filter_counts_for_institution(ncses_remapped["all"], inst_norm)
        p_all = filter_counts_for_institution(pq["all"], inst_norm)
        m_all = filter_counts_for_institution(matched["all"], inst_norm)
        overall = group_payload(n_all, p_all, m_all)
        if not overall:
            continue
        name = candidate_display.get(inst_norm, inst_norm)
        row = {
            "institution": name,
            "institution_norm": inst_norm,
            "ncses": overall[0]["ncses"],
            "proquest": overall[0]["proquest"],
            "matched": overall[0]["matched"],
            "pq_ncses_coverage": overall[0]["pq_ncses_coverage"],
            "matched_ncses_coverage": overall[0]["matched_ncses_coverage"],
            "matched_pq_coverage": overall[0]["matched_pq_coverage"],
        }
        institution_rows.append(row)
        institution_payload.append(
            {
                "name": name,
                "carnegie_unitid": "|".join(sorted(pq.get("unitids", {}).get(inst_norm, set()) | matched.get("unitids", {}).get(inst_norm, set()))),
                "views": {
                    "overall": overall,
                    "broad": group_payload(
                        filter_counts_for_institution(ncses_remapped["broad"], inst_norm),
                        filter_counts_for_institution(pq["broad"], inst_norm),
                        filter_counts_for_institution(matched["broad"], inst_norm),
                        broad_display,
                    ),
                    "major": group_payload(
                        filter_counts_for_institution(ncses_remapped["major"], inst_norm),
                        filter_counts_for_institution(pq["major"], inst_norm),
                        filter_counts_for_institution(matched["major"], inst_norm),
                        major_display,
                    ),
                },
            }
        )

    institution_rows.sort(key=lambda row: (-int(row["ncses"]), str(row["institution"])))
    institution_payload.sort(key=lambda row: (-int(row["views"]["overall"][0]["ncses"]), str(row["name"])))

    field_rows = []
    for group in national["views"]["broad"]:
        field_rows.append({key: group[key] for key in ["field", "ncses", "proquest", "matched", "pq_ncses_coverage", "matched_ncses_coverage", "matched_pq_coverage"]})

    overmatch_rows = []
    for row in institution_rows:
        if row["ncses"] and (row["proquest"] > row["ncses"] or row["matched"] > row["ncses"]):
            overmatch_rows.append(row)
    overmatch_rows.sort(key=lambda row: max(row["proquest"] - row["ncses"], row["matched"] - row["ncses"]), reverse=True)

    matched_institutions = sum(1 for row in crosswalk.values() if row["carnegie_institution_norm"])
    return {
        "summary": {
            "year_min": YEAR_MIN,
            "year_max": YEAR_MAX,
            "ncses_institutions": len(ncses["inst_display"]),
            "matched_ncses_institutions": matched_institutions,
            "unmatched_ncses_institutions": len(ncses["inst_display"]) - matched_institutions,
            "proquest_records": sum(pq["all"].values()),
            "matched_proquest_records": sum(matched["all"].values()),
            "ncses_records": sum(ncses["all"].values()),
            "excluded_broad_fields": sorted(EXCLUDED_BROAD_FIELDS),
        },
        "page": {
            "institutions": [national] + institution_payload,
            "field_summary": field_rows,
            "institution_summary": institution_rows,
            "overmatches": overmatch_rows[:50],
        },
    }


def comparison_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for inst in payload["page"]["institutions"]:
        for view, groups in inst["views"].items():
            for group in groups:
                for year in group["years"]:
                    rows.append(
                        {
                            "institution": inst["name"],
                            "carnegie_unitid": inst.get("carnegie_unitid", ""),
                            "view": view,
                            "field": group["field"],
                            "year": year["year"],
                            "ncses_count": year["ncses"],
                            "proquest_count": year["proquest"],
                            "matched_proquest_count": year["matched"],
                            "pq_ncses_coverage": pct(year["proquest"], year["ncses"]),
                            "matched_ncses_coverage": pct(year["matched"], year["ncses"]),
                            "matched_pq_coverage": pct(year["matched"], year["proquest"]),
                        }
                    )
    return rows


def aggregate_rows(source: str, counts: dict[str, dict[tuple, int]]) -> Iterable[dict[str, object]]:
    for level in ["all", "broad", "major"]:
        for key, count in counts[level].items():
            yield {
                "source": source,
                "level": level,
                "institution_norm": key[0],
                "year": key[1],
                "field_norm": key[2] if len(key) > 2 else "All fields",
                "count": count,
            }


def write_page(payload: dict[str, object]) -> None:
    data_json = json.dumps(payload)
    body = """
    <div class="card"><div id="stats" class="stats"></div></div>
    <div class="card">
      <div class="controls">
        <div class="control">
          <label for="institution-select">Institution</label>
          <select id="institution-select"></select>
        </div>
        <div class="control">
          <label for="view-select">View</label>
          <select id="view-select">
            <option value="overall">Institution overall</option>
            <option value="broad">NSF broad field</option>
            <option value="major">NSF major field</option>
          </select>
        </div>
        <div class="control">
          <label for="field-select">Field</label>
          <select id="field-select"></select>
        </div>
      </div>
      <div id="chart-title" class="title"></div>
      <div id="chart-subtitle" class="subtitle"></div>
      <div class="chart-box">
        <canvas id="coverage-chart" class="chart"></canvas>
        <div id="tooltip" class="tooltip"></div>
      </div>
      <div id="point-details" class="note">Click a line to isolate that source. Click a point to pin the count for that year.</div>
      <div class="note">Counts use graduation years 1980-2019 and the same included field universe as the other dashboards. Excluded fields are social sciences, education, psychology, business, humanities/arts, other non-science and engineering, and blank broad-field rows. ProQuest counts distinct pq_goid_row values, falling back to goid only when pq_goid_row is missing. Matched ProQuest counts distinct matched goid values, falling back to rev_user_id only when goid is missing. NCSES institutions are mapped to Carnegie names by normalized exact/variant matches, selected manual aliases, unique prefix matches, and conservative fuzzy matches.</div>
    </div>
    <div class="card">
      <h2>Field Coverage Summary</h2>
      <div id="field-table"></div>
    </div>
    <div class="card">
      <h2>Institution Coverage Summary</h2>
      <div id="institution-table"></div>
      <div class="note">Coverage is shown directly; rows are not framed as missing people. Values above 100% can occur when NCSES/ProQuest taxonomy or institution mappings differ.</div>
    </div>
    <div class="card">
      <h2>Possible Overmatches</h2>
      <div id="overmatch-table"></div>
    </div>
    """
    script = f"""
  <script>
    const DATA = {data_json};
    const fmt = n => Number(n || 0).toLocaleString();
    const pct = x => (Number(x || 0) * 100).toFixed(1) + '%';
    const institutions = DATA.page.institutions || [];
    const institutionSelect = document.getElementById('institution-select');
    const viewSelect = document.getElementById('view-select');
    const fieldSelect = document.getElementById('field-select');
    const tooltip = document.getElementById('tooltip');
    const pointDetails = document.getElementById('point-details');
    let hoverPoints = [];
    let hoverSegments = [];
    let selectedSeries = null;

    function table(headers, rows) {{
      return '<table><thead><tr>' + headers.map(h => `<th>${{h}}</th>`).join('') + '</tr></thead><tbody>' +
        rows.map(r => '<tr>' + r.map(c => `<td>${{c}}</td>`).join('') + '</tr>').join('') + '</tbody></table>';
    }}
    function selectedInstitution() {{
      return institutions[Number(institutionSelect.value || 0)];
    }}
    function selectedGroups() {{
      const inst = selectedInstitution();
      return ((inst && inst.views && inst.views[viewSelect.value]) || []);
    }}
    function selectedGroup() {{
      return selectedGroups()[Number(fieldSelect.value || 0)];
    }}
    function setStats() {{
      const s = DATA.summary || {{}};
      document.getElementById('stats').innerHTML = [
        ['NCSES PhDs', fmt(s.ncses_records)],
        ['ProQuest pq_goid_row users', fmt(s.proquest_records)],
        ['Matched ProQuest PhDs', fmt(s.matched_proquest_records)],
        ['Matched NCSES institutions', fmt(s.matched_ncses_institutions) + ' / ' + fmt(s.ncses_institutions)],
        ['Years', s.year_min + '-' + s.year_max]
      ].map(([label,value]) => `<div class="stat"><div class="value">${{value}}</div><div class="label">${{label}}</div></div>`).join('');
    }}
    function fillInstitutions() {{
      institutionSelect.innerHTML = institutions.map((u, i) => {{
        return `<option value="${{i}}">${{u.name}}</option>`;
      }}).join('');
    }}
    function fillFields() {{
      const groups = selectedGroups();
      fieldSelect.disabled = viewSelect.value === 'overall';
      fieldSelect.innerHTML = groups.map((g, i) => `<option value="${{i}}">${{g.field}}</option>`).join('');
      if (!groups.length) fieldSelect.innerHTML = '<option value="0">No data</option>';
      render();
    }}
    function draw(group) {{
      const canvas = document.getElementById('coverage-chart');
      const ctx = canvas.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth || 1100, h = canvas.clientHeight || 460;
      canvas.width = w * dpr; canvas.height = h * dpr; ctx.setTransform(dpr,0,0,dpr,0,0);
      ctx.clearRect(0,0,w,h);
      hoverPoints = [];
      hoverSegments = [];
      if (!group || !group.years || !group.years.length) {{
        ctx.fillStyle = '#666'; ctx.font = '15px Georgia';
        ctx.fillText('No comparable data for this selection.', 20, 40);
        return;
      }}
      const rows = group.years;
      const margin = {{left:76,right:190,top:24,bottom:50}};
      const years = rows.map(r => r.year);
      const maxVal = Math.max(...rows.flatMap(r => [r.ncses, r.proquest, r.matched]), 1);
      const axisMax = Math.ceil(maxVal / 1000) * 1000 || maxVal;
      const x = year => margin.left + (years.length <= 1 ? 0 : (year - years[0]) / (years[years.length - 1] - years[0]) * (w - margin.left - margin.right));
      const y = val => h - margin.bottom - val / axisMax * (h - margin.top - margin.bottom);
      ctx.strokeStyle = '#ddd7ca'; ctx.fillStyle = '#666'; ctx.font = '12px Georgia';
      for (let i=0; i<=5; i++) {{
        const val = axisMax * i / 5, yy = y(val);
        ctx.beginPath(); ctx.moveTo(margin.left, yy); ctx.lineTo(w - margin.right, yy); ctx.stroke();
        ctx.textAlign = 'right'; ctx.fillText(fmt(Math.round(val)), margin.left - 10, yy + 4);
      }}
      const colors = {{ncses:'#c43c39', proquest:'#1f4e79', matched:'#5b8e7d'}};
      const labels = {{ncses:'NCSES', proquest:'ProQuest', matched:'Matched ProQuest'}};
      const keys = ['ncses','proquest','matched'];
      const selectedVisible = selectedSeries && keys.includes(selectedSeries);
      if (!selectedVisible) selectedSeries = null;
      const drawKeys = selectedSeries ? [...keys.filter(k => k !== selectedSeries), selectedSeries] : keys;
      drawKeys.forEach(key => {{
        const isSelected = !selectedSeries || key === selectedSeries;
        ctx.globalAlpha = isSelected ? 1 : 0.22;
        ctx.strokeStyle = isSelected ? colors[key] : '#3f3f3f';
        ctx.lineWidth = isSelected ? 3.4 : 1.6;
        ctx.beginPath();
        rows.forEach((r,i) => {{
          const xx=x(r.year), yy=y(r[key]);
          if(i) ctx.lineTo(xx,yy); else ctx.moveTo(xx,yy);
          if (i) {{
            const prev = rows[i - 1];
            hoverSegments.push({{x1:x(prev.year), y1:y(prev[key]), x2:xx, y2:yy, series:key}});
          }}
        }});
        ctx.stroke();
        ctx.fillStyle = isSelected ? colors[key] : '#3f3f3f';
        rows.forEach(r => {{
          const xx = x(r.year), yy = y(r[key]);
          ctx.beginPath(); ctx.arc(xx, yy, isSelected ? 3.5 : 2.4, 0, Math.PI*2); ctx.fill();
          hoverPoints.push({{x:xx, y:yy, series:key, label:labels[key], year:r.year, count:r[key]}});
        }});
        const last = rows[rows.length - 1];
        ctx.textAlign = 'left';
        ctx.fillStyle = isSelected ? colors[key] : '#3f3f3f';
        ctx.fillText(labels[key], w - margin.right + 18, y(last[key]) + 4);
      }});
      ctx.globalAlpha = 1;
      const tickEvery = Math.max(1, Math.ceil(years.length / 8));
      ctx.fillStyle = '#666'; ctx.textAlign = 'center';
      years.forEach((year, i) => {{ if (i % tickEvery === 0 || i === years.length - 1) ctx.fillText(String(year), x(year), h - 18); }});
    }}
    function render() {{
      const inst = selectedInstitution();
      const group = selectedGroup();
      document.getElementById('chart-title').textContent = inst ? inst.name : '';
      document.getElementById('chart-subtitle').textContent = group ? `${{viewSelect.options[viewSelect.selectedIndex].text}} · ${{group.field}} · PQ/NCSES ${{pct(group.pq_ncses_coverage)}} · Matched/NCSES ${{pct(group.matched_ncses_coverage)}}` : '';
      draw(group);
      renderPointDetails(null);
    }}
    function renderPointDetails(point) {{
      if (!point) {{
        pointDetails.innerHTML = 'Click a line to isolate that source. Click a point to pin the count for that year.';
        return;
      }}
      pointDetails.innerHTML = `<strong>${{point.label}} · ${{point.year}}</strong>: ${{fmt(point.count)}} PhDs`;
    }}
    function nearestPoint(event) {{
      const rect = event.target.getBoundingClientRect();
      const mx = event.clientX - rect.left, my = event.clientY - rect.top;
      let best = null, bestDist = 9999;
      hoverPoints.forEach(p => {{
        const d = Math.hypot(mx - p.x, my - p.y);
        if (d < bestDist) {{ best = p; bestDist = d; }}
      }});
      return {{point: best, distance: bestDist, x: mx, y: my}};
    }}
    function distanceToSegment(px, py, seg) {{
      const dx = seg.x2 - seg.x1;
      const dy = seg.y2 - seg.y1;
      const lenSq = dx * dx + dy * dy;
      if (!lenSq) return Math.hypot(px - seg.x1, py - seg.y1);
      const t = Math.max(0, Math.min(1, ((px - seg.x1) * dx + (py - seg.y1) * dy) / lenSq));
      return Math.hypot(px - (seg.x1 + t * dx), py - (seg.y1 + t * dy));
    }}
    function nearestSeriesHit(event) {{
      const pointHit = nearestPoint(event);
      let bestSegment = null, bestSegmentDist = 9999;
      hoverSegments.forEach(seg => {{
        const d = distanceToSegment(pointHit.x, pointHit.y, seg);
        if (d < bestSegmentDist) {{ bestSegment = seg; bestSegmentDist = d; }}
      }});
      return {{
        ...pointHit,
        segment: bestSegment,
        segmentDistance: bestSegmentDist,
        series: pointHit.distance <= 14 && pointHit.point ? pointHit.point.series : (bestSegmentDist <= 8 && bestSegment ? bestSegment.series : null)
      }};
    }}
    function renderTables() {{
      document.getElementById('field-table').innerHTML = table(
        ['Field','NCSES','ProQuest','Matched ProQuest','PQ/NCSES','Matched/NCSES','Matched/PQ'],
        DATA.page.field_summary.map(r => [r.field, fmt(r.ncses), fmt(r.proquest), fmt(r.matched), pct(r.pq_ncses_coverage), pct(r.matched_ncses_coverage), pct(r.matched_pq_coverage)])
      );
      document.getElementById('institution-table').innerHTML = table(
        ['Institution','NCSES','ProQuest','Matched ProQuest','PQ/NCSES','Matched/NCSES','Matched/PQ'],
        DATA.page.institution_summary.slice(0, 75).map(r => [r.institution, fmt(r.ncses), fmt(r.proquest), fmt(r.matched), pct(r.pq_ncses_coverage), pct(r.matched_ncses_coverage), pct(r.matched_pq_coverage)])
      );
      document.getElementById('overmatch-table').innerHTML = table(
        ['Institution','NCSES','ProQuest','Matched ProQuest','PQ/NCSES','Matched/NCSES'],
        DATA.page.overmatches.map(r => [r.institution, fmt(r.ncses), fmt(r.proquest), fmt(r.matched), pct(r.pq_ncses_coverage), pct(r.matched_ncses_coverage)])
      );
    }}
    document.getElementById('coverage-chart').addEventListener('mousemove', (event) => {{
      const hit = nearestPoint(event);
      if (!hit.point || hit.distance > 12) {{
        tooltip.style.opacity = 0;
        return;
      }}
      tooltip.innerHTML = `<strong>${{hit.point.label}}</strong><br>${{hit.point.year}}: ${{fmt(hit.point.count)}}<br>Click to isolate`;
      tooltip.style.left = hit.x + 'px';
      tooltip.style.top = hit.y + 'px';
      tooltip.style.opacity = 1;
    }});
    document.getElementById('coverage-chart').addEventListener('click', (event) => {{
      const hit = nearestSeriesHit(event);
      selectedSeries = hit.series;
      render();
      if (hit.point && hit.distance <= 14) renderPointDetails(hit.point);
    }});
    document.getElementById('coverage-chart').addEventListener('mouseleave', () => tooltip.style.opacity = 0);
    institutionSelect.addEventListener('change', () => {{ selectedSeries = null; fillFields(); }});
    viewSelect.addEventListener('change', () => {{ selectedSeries = null; fillFields(); }});
    fieldSelect.addEventListener('change', () => {{ selectedSeries = null; render(); }});
    window.addEventListener('resize', render);
    setStats();
    fillInstitutions();
    fillFields();
    renderTables();
  </script>
"""
    html = common.html_shell(
        "NCSES / ProQuest Coverage",
        "Doctorate counts by graduation year, institution, and NSF field across NCSES, ProQuest baseline, and matched ProQuest data.",
        body,
        script,
    )
    common.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(html, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = latest_ncses_zip()
    ncses_rows = read_ncses_rows(zip_path)
    ncses, ncses_diag = build_ncses_counts(ncses_rows)
    pq, pq_diag = build_proquest_counts()
    matched, matched_diag = build_matched_counts()
    candidate_counts, candidate_display, candidate_unitids = build_candidate_institutions(pq, matched)
    crosswalk = build_crosswalk(ncses["inst_display"], candidate_counts, candidate_display, candidate_unitids)
    ncses_remapped = {
        "all": remap_ncses_counts(ncses["all"], crosswalk),
        "broad": remap_ncses_counts(ncses["broad"], crosswalk),
        "major": remap_ncses_counts(ncses["major"], crosswalk),
    }
    payload = build_page_payload(ncses, ncses_remapped, pq, matched, crosswalk)
    payload["summary"].update(
        {
            "source_zip": str(zip_path),
            "proquest_source": str(PQ_CSV),
            "ncses_rows": ncses_diag["ncses_rows"],
            "proquest_rows": pq_diag["pq_rows"],
            "matched_crosswalk_safe_pairs": matched_diag["crosswalk_safe_pairs"],
            "matched_crosswalk_ambiguous_pairs": matched_diag["crosswalk_ambiguous_pairs"],
            "comparison_cells": len(comparison_rows(payload)),
        }
    )

    common.write_csv(
        CROSSWALK_CSV,
        [
            "ncses_institution",
            "ncses_institution_norm",
            "carnegie_institution",
            "carnegie_institution_norm",
            "carnegie_unitid",
            "match_method",
            "match_score",
            "candidate_record_count",
        ],
        crosswalk.values(),
    )
    common.write_csv(
        COMPARISON_CSV,
        [
            "institution",
            "carnegie_unitid",
            "view",
            "field",
            "year",
            "ncses_count",
            "proquest_count",
            "matched_proquest_count",
            "pq_ncses_coverage",
            "matched_ncses_coverage",
            "matched_pq_coverage",
        ],
        comparison_rows(payload),
    )
    common.write_csv(
        NCSES_AGG_CSV,
        ["source", "level", "institution_norm", "year", "field_norm", "count"],
        aggregate_rows("ncses", ncses_remapped),
    )
    common.write_csv(
        PQ_AGG_CSV,
        ["source", "level", "institution_norm", "year", "field_norm", "count"],
        aggregate_rows("proquest", pq),
    )
    common.write_csv(
        OUR_AGG_CSV,
        ["source", "level", "institution_norm", "year", "field_norm", "count"],
        aggregate_rows("matched_proquest", matched),
    )

    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_page(payload)
    print(f"Wrote {DOC_PATH}")
    print(
        "NCSES / ProQuest / matched totals: "
        f"{payload['summary']['ncses_records']:,} / "
        f"{payload['summary']['proquest_records']:,} / "
        f"{payload['summary']['matched_proquest_records']:,}"
    )


if __name__ == "__main__":
    main()
