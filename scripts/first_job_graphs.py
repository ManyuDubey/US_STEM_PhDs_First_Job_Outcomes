#!/usr/bin/env python3
"""Improve first-job classifications and generate advisor-ready SVG charts."""

from __future__ import annotations

import csv
import json
import math
import os
import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Sequence, Tuple


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_CSV = os.path.join(ROOT, "codex_data", "first_job_after_phd_classified.csv")
OUT_DIR = os.path.join(ROOT, "outputs", "first_job_graphs")
OUT_CSV = os.path.join(OUT_DIR, "first_job_after_phd_classified_v2.csv")
SED_BROAD_XLSX = os.path.join(OUT_DIR, "nsf25349-tab001-002.xlsx")
OVERRIDES_JSON = os.path.join(ROOT, "config", "first_job_overrides.json")
SED_TAXONOMY_XLSX = os.path.join(ROOT, "codex_data", "nsf25349-taba-004.xlsx")


ORG_ORDER = [
    "University / Academic Institution",
    "Research Institute / Nonprofit",
    "Hospital / Health System",
    "Government Lab",
    "Government Agency / Public Sector",
    "Listed Company",
    "Startup / VC-backed Private Firm",
    "Business (Unclassified)",
    "Self-Employed / Independent",
    "Other / Unclassified",
]

AGGREGATE_ORDER = [
    "Academia",
    "Research Institute / Nonprofit",
    "Hospital / Health",
    "Government",
    "Listed Company",
    "Startup / VC-backed Private Firm",
    "Business (Unclassified)",
    "Self-Employed / Independent",
    "Other / Unclassified",
]

DEFAULT_FIELD_ORDER = [
    "Biological and biomedical sciences",
    "Engineering",
    "Physical sciences",
    "Computer and information sciences",
    "Mathematics and statistics",
    "Health sciences",
    "Agricultural sciences and natural resources",
    "Geosciences, atmospheric, and ocean sciences",
]
FIELD_ORDER = list(DEFAULT_FIELD_ORDER)
MAJOR_ORDER: List[str] = []

COLORS = {
    "University / Academic Institution": "#1f4e79",
    "Research Institute / Nonprofit": "#5b8e7d",
    "Hospital / Health System": "#a23b72",
    "Government Lab": "#6c5b7b",
    "Government Agency / Public Sector": "#4f6d7a",
    "Listed Company": "#d97b29",
    "Startup / VC-backed Private Firm": "#c43c39",
    "Business (Unclassified)": "#8c7a5b",
    "Self-Employed / Independent": "#7f7f7f",
    "Other / Unclassified": "#c9c9c9",
    "Academia": "#1f4e79",
    "Hospital / Health": "#a23b72",
    "Government": "#5f6b8a",
    "Biological and biomedical sciences": "#1f4e79",
    "Engineering": "#c43c39",
    "Physical sciences": "#d97b29",
    "Computer and information sciences": "#3b7a57",
    "Mathematics and statistics": "#6c5b7b",
    "Health sciences": "#a23b72",
    "Agricultural sciences and natural resources": "#7a8f3b",
    "Geosciences, atmospheric, and ocean sciences": "#2f6f9f",
    "Multidisciplinary/ interdisciplinary sciences": "#7f6a9a",
    "Multidisciplinary sciences": "#7f6a9a",
}

DISPLAY_LABELS = {
    "Startup / VC-backed Private Firm": "Startup / VC-Backed",
}

SCHEMA_FIELD_ALIASES = {
    "Multidisciplinary/ interdisciplinary sciences": "Multidisciplinary sciences",
}

OVERRIDES = {
    "org_name_overrides": {},
    "classification_exact_overrides": {},
    "classification_regex_overrides": [],
}


PUBLIC_NAME_PATTERNS = [
    r"\bibm\b",
    r"\bmerck\b",
    r"\bpfizer\b",
    r"\bbristol[- ]?myers squibb\b",
    r"\bexxon ?mobil\b",
    r"\beli lilly\b",
    r"\bamgen\b",
    r"\btexas instruments\b",
    r"\bapplied materials\b",
    r"\bprocter ?&? ?gamble\b",
    r"\bford motor\b",
    r"\bgeneral motors\b",
    r"\blam research\b",
    r"\bsamsung electronics\b",
    r"\bgsk\b",
    r"\bnovartis\b",
    r"\bchevron\b",
    r"\babbvie\b",
    r"\bschlumberger\b",
    r"\blockheed martin\b",
    r"\bshell\b",
    r"\bseagate\b",
    r"\bthermo fisher\b",
    r"\babbott\b",
    r"\bjohnson ?&? ?johnson\b",
    r"\bboeing\b",
    r"\bglaxosmithkline\b",
    r"\bmotorola\b",
    r"\bnorthrop grumman\b",
    r"\bglobalfoundries\b",
    r"\bbasf\b",
    r"\bmicron\b",
    r"\bcaterpillar\b",
    r"\braytheon\b",
    r"\bastrazeneca\b",
    r"\bamd\b",
    r"\bmedtronic\b",
    r"\bhoneywell\b",
    r"\basml\b",
    r"\bciti\b",
    r"\bhewlett[- ]?packard\b",
    r"\bhp\b",
    r"\bge\b",
    r"\bge global research\b",
    r"\bgoogle\b",
    r"\balphabet\b",
    r"\bmorgan stanley\b",
    r"\bat ?&? ?t\b",
    r"\bcorning\b",
    r"\bdow chemical\b",
    r"\bthe dow chemical company\b",
    r"\bkla[- ]?tencor\b",
    r"\bbloomberg\b",
    r"\bamazon web services\b",
    r"\bamazon\b",
]

RESEARCH_NONPROFIT_PATTERNS = [
    r"\bscripps research\b",
    r"\bdana[- ]farber\b",
    r"\bhoward hughes medical institute\b",
    r"\bhhmi\b",
    r"\bsalk institute\b",
    r"\bfred hutch(?:inson)?\b",
    r"\bcold spring harbor laboratory\b",
    r"\bwoods hole oceanographic institution\b",
    r"\bsri international\b",
    r"\bmitre\b",
    r"\bthe aerospace corporation\b",
    r"\bbroad institute\b",
    r"\bstowers institute\b",
    r"\bjanelia\b",
    r"\bburnham institute\b",
    r"\bbattelle\b",
]

UNIVERSITY_PATTERNS = [
    r"\buniversity\b",
    r"\bcollege\b",
    r"\bschool of\b",
    r"\bpolytechnic\b",
    r"\binstitute of technology\b",
    r"\bcolorado school of mines\b",
    r"\bharvard t h chan school of public health\b",
]

GOV_LAB_PATTERNS = [
    r"\bnational renewable energy laboratory\b",
    r"\bnational (?:lab|laboratory)\b",
    r"\bargonne\b",
    r"\bsandia\b",
    r"\blawrence (?:berkeley|livermore)\b",
    r"\blos alamos\b",
    r"\boak ridge\b",
    r"\bpacific northwest national laboratory\b",
    r"\bnrel\b",
    r"\bnih\b",
    r"\bnist\b",
    r"\bcdc\b",
    r"\bnoaa\b",
    r"\busda ars\b",
    r"\bus geological survey\b",
    r"\busgs\b",
]

GOV_PUBLIC_PATTERNS = [
    r"\bdepartment of\b",
    r"\bministry of\b",
    r"\bbureau of\b",
    r"\bagency\b",
    r"\bcity of\b",
    r"\bcounty of\b",
    r"\bstate of\b",
    r"\barmy\b",
    r"\bnavy\b",
    r"\bair force\b",
    r"\bfederal\b",
    r"\bpublic health service\b",
]

HOSPITAL_PATTERNS = [
    r"\bhospital\b",
    r"\bhealth system\b",
    r"\bmedical center\b",
    r"\bclinic\b",
    r"\bcancer center\b",
    r"\bchildren'?s\b.*\bhospital\b",
    r"\bva medical center\b",
]

SELF_EMPLOYED_PATTERNS = [
    r"\bself employed\b",
    r"\bself-employed\b",
    r"\bfreelance\b",
    r"\bindependent consultant\b",
    r"\bconsultant\b",
]


def text_join(row: Dict[str, str]) -> str:
    parts = [
        row.get("company_cleaned", ""),
        row.get("company_raw", ""),
        row.get("revelio_company", ""),
        row.get("revelio_primary_name", ""),
        row.get("revelio_ultimate_parent_name", ""),
        row.get("ultimate_parent_rcid_name", ""),
        row.get("compustat_company_name", ""),
        row.get("pitchbook_companyname", ""),
    ]
    joined = " | ".join(x for x in parts if x)
    return re.sub(r"\s+", " ", joined.lower()).strip()


def load_overrides(path: str = OVERRIDES_JSON) -> Dict[str, object]:
    if not os.path.exists(path):
        return {
            "org_name_overrides": {},
            "classification_exact_overrides": {},
            "classification_regex_overrides": [],
        }
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {
        "org_name_overrides": data.get("org_name_overrides", {}),
        "classification_exact_overrides": data.get("classification_exact_overrides", {}),
        "classification_regex_overrides": data.get("classification_regex_overrides", []),
    }


def canonical_org_name(row: Dict[str, str]) -> str:
    candidates = [
        row.get("revelio_primary_name", "").strip(),
        row.get("revelio_company", "").strip(),
        row.get("ultimate_parent_rcid_name", "").strip(),
        row.get("company_raw", "").strip(),
        row.get("company_cleaned", "").strip(),
    ]
    name = next((x for x in candidates if x), "")
    return re.sub(r"\s+", " ", name).strip(" |,;")


def any_match(text: str, patterns: Sequence[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def has_public_identifier(row: Dict[str, str]) -> bool:
    fields = [
        "ticker",
        "exchange_name",
        "cusip",
        "revelio_ticker",
        "revelio_exchange_name",
        "revelio_cusip",
        "revelio_isin",
        "revelio_cik",
        "revelio_gvkey",
        "compustat_gvkey",
        "compustat_cusip",
        "compustat_cik",
        "compustat_ticker",
    ]
    return any((row.get(field) or "").strip() for field in fields)


def to_int(value: str) -> int | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def classify_v2(row: Dict[str, str]) -> Tuple[str, str, str]:
    original = row.get("first_job_org_type", "") or "Other / Unclassified"
    text = text_join(row)
    classification_source = row.get("classification_source", "")
    pitchbook_source = row.get("pitchbook_join_source", "")
    org_name = canonical_org_name(row)
    org_name_lower = org_name.lower()

    exact_override = OVERRIDES["classification_exact_overrides"].get(org_name_lower)
    if isinstance(exact_override, dict) and exact_override.get("org_type"):
        return (
            exact_override["org_type"],
            exact_override.get("source", "override_exact"),
            exact_override.get("confidence", "high"),
        )

    for override in OVERRIDES["classification_regex_overrides"]:
        pattern = override.get("pattern", "")
        if pattern and re.search(pattern, text):
            return (
                override["org_type"],
                override.get("source", "override_regex"),
                override.get("confidence", "high"),
            )

    if any_match(text, SELF_EMPLOYED_PATTERNS):
        return (
            "Self-Employed / Independent",
            "v2_self_employed_name_rule",
            "medium",
        )

    if original == "Listed Company - IPO Date Missing":
        return ("Listed Company", "v2_collapse_public_missing_ipo", "medium")

    if original == "Startup / VC-backed Private Firm":
        return (original, classification_source or "startup_existing_rule", "high")

    if any_match(text, GOV_LAB_PATTERNS):
        return ("Government Lab", "v2_government_lab_name_rule", "medium")

    if any_match(text, GOV_PUBLIC_PATTERNS):
        return (
            "Government Agency / Public Sector",
            "v2_government_public_name_rule",
            "medium",
        )

    if any_match(text, HOSPITAL_PATTERNS):
        return ("Hospital / Health System", "v2_hospital_name_rule", "medium")

    if any_match(text, RESEARCH_NONPROFIT_PATTERNS):
        return (
            "Research Institute / Nonprofit",
            "v2_research_nonprofit_name_rule",
            "medium",
        )

    if any_match(text, UNIVERSITY_PATTERNS):
        return (
            "University / Academic Institution",
            "v2_university_name_rule",
            "medium",
        )

    if has_public_identifier(row) and (
        "public" in classification_source.lower()
        or "compustat" in classification_source.lower()
        or any_match(text, PUBLIC_NAME_PATTERNS)
    ):
        return ("Listed Company", "v2_public_identifier_rule", "medium")

    if any_match(text, PUBLIC_NAME_PATTERNS):
        return ("Listed Company", "v2_public_name_rule", "medium")

    if original == "Business (Unclassified)" and pitchbook_source:
        return ("Startup / VC-backed Private Firm", "v2_pitchbook_escalation", "medium")

    if original in {"Other / Unclassified", "Business (Unclassified)"}:
        return (original, classification_source or "unchanged_weak_rule", "low")

    return (original, classification_source or "unchanged_original", "high")


def aggregate_org_type(org_type: str) -> str:
    if org_type == "University / Academic Institution":
        return "Academia"
    if org_type in {"Government Lab", "Government Agency / Public Sector"}:
        return "Government"
    if org_type == "Hospital / Health System":
        return "Hospital / Health"
    return org_type


def clean_field(field: str) -> str:
    field = (field or "").strip()
    if not field or field in {"Social sciences", "Education", "Psychology", "Business", "Humanities", "Visual and performing arts", "Other non-science and engineering"}:
        return "Other / Small Fields"
    if field == "Multidisciplinary/ interdisciplinary sciences":
        return "Multidisciplinary sciences"
    return field


def best_org_name(row: Dict[str, str]) -> str:
    name = canonical_org_name(row)
    if not name:
        return name
    override = OVERRIDES["org_name_overrides"].get(name.lower())
    return override if isinstance(override, str) and override.strip() else name


def write_csv(path: str, fieldnames: List[str], rows: Iterable[Dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def pct(num: int, den: int) -> str:
    return f"{(100.0 * num / den):.1f}%" if den else "0.0%"


def load_and_recode() -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    os.makedirs(OUT_DIR, exist_ok=True)
    rows: List[Dict[str, str]] = []
    movement = Counter()
    old_counts = Counter()
    new_counts = Counter()
    changed_examples: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    year_totals = Counter()

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        out_fields = fieldnames + [
            "first_job_org_type_v2",
            "classification_source_v2",
            "classification_confidence_v2",
            "org_type_aggregate_v2",
            "nsf_broad_clean",
        ]
        for row in reader:
            old = row.get("first_job_org_type", "") or "Other / Unclassified"
            new, src, conf = classify_v2(row)
            row["first_job_org_type_v2"] = new
            row["classification_source_v2"] = src
            row["classification_confidence_v2"] = conf
            row["org_type_aggregate_v2"] = aggregate_org_type(new)
            row["nsf_broad_clean"] = clean_field(row.get("nsf_broad", ""))
            rows.append(row)

            old_counts[old] += 1
            new_counts[new] += 1
            movement[(old, new)] += 1
            year = to_int(row.get("grad_year"))
            if year is not None:
                year_totals[year] += 1

            if old != new and len(changed_examples[(old, new)]) < 5:
                changed_examples[(old, new)].append(
                    f"{row.get('company_raw') or row.get('company_cleaned') or row.get('revelio_primary_name')}"
                )

    write_csv(OUT_CSV, out_fields, rows)
    return rows, {
        "movement": movement,
        "old_counts": old_counts,
        "new_counts": new_counts,
        "changed_examples": changed_examples,
        "year_totals": year_totals,
    }


def classification_rank(row: Dict[str, str]) -> int:
    org_type = row.get("first_job_org_type_v2", "")
    confidence = row.get("classification_confidence_v2", "")
    source = row.get("classification_source_v2", "")
    rank = 0
    if org_type and org_type != "Other / Unclassified":
        rank += 10
    if confidence == "high":
        rank += 6
    elif confidence == "medium":
        rank += 3
    if "override" in source:
        rank += 2
    if row.get("rcid", "").strip():
        rank += 4
    if row.get("revelio_primary_name", "").strip():
        rank += 2
    if row.get("company_raw", "").strip():
        rank += 1
    return rank


def dedupe_rows_by_rev_user_id(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    chosen: Dict[str, Dict[str, str]] = {}
    for row in rows:
        rev_user_id = (row.get("rev_user_id") or "").strip()
        if not rev_user_id:
            continue
        current = chosen.get(rev_user_id)
        if current is None:
            chosen[rev_user_id] = row
            continue

        row_score = (
            classification_rank(row),
            1 if row.get("pq_row_id", "").strip() else 0,
            -(to_int(row.get("first_job_year")) or 9999),
            row.get("pq_row_id", ""),
        )
        current_score = (
            classification_rank(current),
            1 if current.get("pq_row_id", "").strip() else 0,
            -(to_int(current.get("first_job_year")) or 9999),
            current.get("pq_row_id", ""),
        )
        if row_score > current_score:
            chosen[rev_user_id] = row
    return list(chosen.values())


def yearly_distinct_id_count_table(
    rows: List[Dict[str, str]],
    group_field: str,
    id_field: str,
    allowed_groups: Sequence[str] | None = None,
) -> Dict[int, Dict[str, int]]:
    allowed = set(allowed_groups or [])
    table_sets: Dict[int, Dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        year = to_int(row.get("grad_year"))
        group = (row.get(group_field) or "").strip()
        id_value = (row.get(id_field) or "").strip()
        if year is None or not group or not id_value:
            continue
        if year > 2024:
            continue
        if allowed and group not in allowed:
            continue
        table_sets[year][group].add(id_value)
    out: Dict[int, Dict[str, int]] = defaultdict(dict)
    for year, group_map in table_sets.items():
        for group, ids in group_map.items():
            out[year][group] = len(ids)
    return out


def escape_xml(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def svg_open(width: int, height: int) -> List[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f7f4ef"/>',
    ]


def svg_close(parts: List[str], path: str) -> None:
    parts.append("</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


def add_text(parts: List[str], x: float, y: float, text: str, size: int = 14,
             weight: str = "normal", anchor: str = "start", fill: str = "#222") -> None:
    parts.append(
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Georgia, Times New Roman, serif" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" fill="{fill}">{escape_xml(text)}</text>'
    )


def display_label(text: str) -> str:
    return DISPLAY_LABELS.get(text, text)


def schema_alias(text: str) -> str:
    return SCHEMA_FIELD_ALIASES.get(text, text)


def add_line(parts: List[str], x1: float, y1: float, x2: float, y2: float,
             stroke: str = "#555", width: float = 1.0, dash: str | None = None) -> None:
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    parts.append(
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{width}"{extra}/>'
    )


def add_rect(parts: List[str], x: float, y: float, w: float, h: float,
             fill: str, stroke: str | None = None, rx: float = 0.0) -> None:
    extra = f' stroke="{stroke}" stroke-width="1"' if stroke else ""
    parts.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" rx="{rx}"{extra}/>'
    )


def add_polyline(parts: List[str], pts: Sequence[Tuple[float, float]], stroke: str,
                 width: float = 2.5) -> None:
    coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    parts.append(
        f'<polyline fill="none" stroke="{stroke}" stroke-width="{width}" points="{coords}"/>'
    )


def add_circle(parts: List[str], x: float, y: float, r: float, fill: str, tooltip: str | None = None) -> None:
    if tooltip:
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{fill}" stroke="#ffffff" stroke-width="1.2">'
            f"<title>{escape_xml(tooltip)}</title></circle>"
        )
    else:
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{fill}" stroke="#ffffff" stroke-width="1.2"/>'
        )


def chart_title(parts: List[str], width: int, title: str, subtitle: str) -> None:
    add_text(parts, 40, 34, title, size=24, weight="bold")
    add_text(parts, 40, 58, subtitle, size=12, fill="#555")
    add_line(parts, 40, 70, width - 40, 70, stroke="#d8d2c4", width=1.2)


def yearly_share_table(rows: List[Dict[str, str]], category_field: str) -> Dict[int, Dict[str, int]]:
    table: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        year = to_int(row.get("grad_year"))
        category = row.get(category_field, "")
        if year is None or not category:
            continue
        if year > 2024:
            continue
        table[year][category] += 1
    return table


def yearly_count_table(rows: List[Dict[str, str]], group_field: str, allowed_groups: Sequence[str] | None = None) -> Dict[int, Dict[str, int]]:
    allowed = set(allowed_groups or [])
    table: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        year = to_int(row.get("grad_year"))
        group = (row.get(group_field) or "").strip()
        if year is None or not group:
            continue
        if year > 2024:
            continue
        if allowed and group not in allowed:
            continue
        table[year][group] += 1
    return table


def field_share_table(rows: List[Dict[str, str]], category_field: str) -> Dict[str, Dict[str, int]]:
    table: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        field = row.get("nsf_broad_clean", "")
        category = row.get(category_field, "")
        if not field or field == "Other / Small Fields" or not category:
            continue
        table[field][category] += 1
    return table


def field_year_share_table(rows: List[Dict[str, str]], category_field: str) -> Dict[str, Dict[int, Dict[str, int]]]:
    table: Dict[str, Dict[int, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for row in rows:
        field = row.get("nsf_broad_clean", "")
        year = to_int(row.get("grad_year"))
        category = row.get(category_field, "")
        if not field or field == "Other / Small Fields" or year is None or not category:
            continue
        if year > 2024:
            continue
        table[field][year][category] += 1
    return table


def group_year_share_table(
    rows: List[Dict[str, str]],
    group_field: str,
    category_field: str,
    exclude_values: Sequence[str] | None = None,
) -> Dict[str, Dict[int, Dict[str, int]]]:
    excluded = set(exclude_values or [])
    table: Dict[str, Dict[int, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for row in rows:
        group = (row.get(group_field) or "").strip()
        year = to_int(row.get("grad_year"))
        category = row.get(category_field, "")
        if not group or group in excluded or year is None or not category:
            continue
        if year > 2024:
            continue
        table[group][year][category] += 1
    return table


def top_orgs_by_group(
    rows: List[Dict[str, str]],
    group_field: str,
    exclude_values: Sequence[str] | None = None,
    top_n: int = 10,
) -> Dict[str, List[Dict[str, object]]]:
    excluded = set(exclude_values or [])
    counters: Dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        group = (row.get(group_field) or "").strip()
        if not group or group in excluded:
            continue
        org = best_org_name(row)
        if not org:
            continue
        counters[group][org] += 1
    out: Dict[str, List[Dict[str, object]]] = {}
    for group, counter in counters.items():
        out[group] = [{"name": name, "count": count} for name, count in counter.most_common(top_n)]
    return out


def org_year_counts_by_group(
    rows: List[Dict[str, str]],
    group_field: str,
    exclude_values: Sequence[str] | None = None,
) -> Dict[str, Dict[int, Dict[str, int]]]:
    excluded = set(exclude_values or [])
    counts: Dict[str, Dict[int, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for row in rows:
        group = (row.get(group_field) or "").strip()
        year = to_int(row.get("grad_year"))
        if not group or group in excluded or year is None:
            continue
        if year > 2024:
            continue
        org = best_org_name(row)
        if not org:
            continue
        counts[group][year][org] += 1
    return counts


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def render_stacked_share_chart(
    data: Dict[int, Dict[str, int]],
    categories: Sequence[str],
    title: str,
    subtitle: str,
    path: str,
) -> None:
    width, height = 1400, 760
    left, right, top, bottom = 90, 60, 110, 100
    plot_w = width - left - right
    plot_h = height - top - bottom
    years = sorted(data)
    parts = svg_open(width, height)
    chart_title(parts, width, title, subtitle)

    for ytick in range(0, 101, 20):
        y = top + plot_h - (ytick / 100.0) * plot_h
        add_line(parts, left, y, left + plot_w, y, stroke="#ddd7ca", width=1)
        add_text(parts, left - 12, y + 5, f"{ytick}%", size=12, anchor="end", fill="#555")

    bar_w = plot_w / max(len(years), 1)
    for idx, year in enumerate(years):
        x = left + idx * bar_w + 1
        year_total = sum(data[year].values())
        running = 0.0
        for cat in categories:
            share = (data[year].get(cat, 0) / year_total) if year_total else 0.0
            h = share * plot_h
            y = top + plot_h - running - h
            add_rect(parts, x, y, max(bar_w - 2, 1), h, COLORS.get(cat, "#bbb"))
            running += h
        if idx % 2 == 0:
            add_text(parts, x + bar_w / 2, top + plot_h + 22, str(year), size=11, anchor="middle", fill="#444")

    add_line(parts, left, top, left, top + plot_h, stroke="#555", width=1.2)
    add_line(parts, left, top + plot_h, left + plot_w, top + plot_h, stroke="#555", width=1.2)
    add_text(parts, width / 2, height - 28, "PhD graduation year", size=14, anchor="middle")
    add_text(parts, 24, top + plot_h / 2, "Share of first jobs", size=14, anchor="middle")

    legend_x = left + plot_w + 10
    legend_y = top + 10
    for idx, cat in enumerate(categories):
        y = legend_y + idx * 24
        add_rect(parts, legend_x, y - 10, 16, 16, COLORS.get(cat, "#bbb"))
        add_text(parts, legend_x + 24, y + 3, display_label(cat), size=12)

    svg_close(parts, path)


def render_line_chart(
    data: Dict[int, Dict[str, int]],
    categories: Sequence[str],
    title: str,
    subtitle: str,
    path: str,
    y_max: float = 0.70,
    show_line_end_labels: bool = False,
) -> None:
    width, height = 1680, 760
    left, right, top, bottom = 130, 420, 110, 90
    plot_w = width - left - right
    plot_h = height - top - bottom
    years = sorted(data)
    ymin, ymax = 0.0, y_max
    parts = svg_open(width, height)
    chart_title(parts, width, title, subtitle)

    ytick = 0.0
    while ytick <= ymax + 1e-9:
        y = top + plot_h - ((ytick - ymin) / (ymax - ymin)) * plot_h
        add_line(parts, left, y, left + plot_w, y, stroke="#ddd7ca", width=1)
        add_text(parts, left - 12, y + 5, f"{int(ytick * 100)}%", size=12, anchor="end", fill="#555")
        ytick += 0.1

    def x_pos(year: int) -> float:
        return left + ((year - years[0]) / max(years[-1] - years[0], 1)) * plot_w

    def y_pos(value: float) -> float:
        return top + plot_h - ((value - ymin) / (ymax - ymin)) * plot_h

    for year in years:
        if year % 2 == 0:
            add_text(parts, x_pos(year), top + plot_h + 22, str(year), size=11, anchor="middle", fill="#444")

    for cat in categories:
        pts = []
        for year in years:
            total = sum(data[year].values())
            share = data[year].get(cat, 0) / total if total else 0.0
            pts.append((x_pos(year), y_pos(share)))
        add_polyline(parts, pts, COLORS.get(cat, "#333"), width=3.0)
        for idx, year in enumerate(years):
            total = sum(data[year].values())
            share = data[year].get(cat, 0) / total if total else 0.0
            tooltip = f"{display_label(cat)}\nGraduation year: {year}\nShare: {share * 100:.1f}%"
            add_circle(parts, pts[idx][0], pts[idx][1], 3.2, COLORS.get(cat, "#333"), tooltip=tooltip)
        if pts and show_line_end_labels:
            lx, ly = pts[-1]
            add_text(parts, lx + 8, ly + 4, cat, size=12, fill=COLORS.get(cat, "#333"))

    add_line(parts, left, top, left, top + plot_h, stroke="#555", width=1.2)
    add_line(parts, left, top + plot_h, left + plot_w, top + plot_h, stroke="#555", width=1.2)
    add_text(parts, width / 2, height - 26, "PhD graduation year", size=14, anchor="middle")
    parts.append(
        f'<g transform="translate(34,{top + plot_h / 2:.1f}) rotate(-90)">'
        f'<text font-family="Georgia, Times New Roman, serif" font-size="14" text-anchor="middle" fill="#222">Share of first jobs</text></g>'
    )

    legend_x = left + plot_w + 32
    legend_y = top + 12
    for idx, cat in enumerate(categories):
        y = legend_y + idx * 24
        add_rect(parts, legend_x, y - 10, 16, 16, COLORS.get(cat, "#bbb"))
        add_text(parts, legend_x + 24, y + 3, cat, size=12)

    svg_close(parts, path)


def render_field_line_chart(
    field: str,
    data: Dict[int, Dict[str, int]],
    categories: Sequence[str],
    title: str,
    subtitle: str,
    path: str,
) -> None:
    render_line_chart(
        data,
        categories,
        title,
        subtitle,
        path,
        y_max=0.80,
        show_line_end_labels=False,
    )


def render_field_stacked_bars(
    data: Dict[str, Dict[str, int]],
    categories: Sequence[str],
    title: str,
    subtitle: str,
    path: str,
) -> None:
    width, height = 1400, 760
    left, right, top, bottom = 110, 60, 110, 170
    plot_w = width - left - right
    plot_h = height - top - bottom
    fields = [field for field in FIELD_ORDER if field in data]
    parts = svg_open(width, height)
    chart_title(parts, width, title, subtitle)

    for ytick in range(0, 101, 20):
        y = top + plot_h - (ytick / 100.0) * plot_h
        add_line(parts, left, y, left + plot_w, y, stroke="#ddd7ca", width=1)
        add_text(parts, left - 12, y + 5, f"{ytick}%", size=12, anchor="end", fill="#555")

    bar_w = plot_w / max(len(fields), 1)
    for idx, field in enumerate(fields):
        x = left + idx * bar_w + 8
        total = sum(data[field].values())
        running = 0.0
        for cat in categories:
            share = data[field].get(cat, 0) / total if total else 0.0
            h = share * plot_h
            y = top + plot_h - running - h
            add_rect(parts, x, y, bar_w - 16, h, COLORS.get(cat, "#bbb"))
            running += h
        label = field.replace(" and ", " & ").replace(", atmospheric, and ", ", ")
        parts.append(
            f'<g transform="translate({x + (bar_w - 16) / 2:.1f},{top + plot_h + 18:.1f}) rotate(32)">'
            f'<text font-family="Georgia, Times New Roman, serif" font-size="12" fill="#444" text-anchor="start">{escape_xml(label)}</text></g>'
        )

    add_line(parts, left, top, left, top + plot_h, stroke="#555", width=1.2)
    add_line(parts, left, top + plot_h, left + plot_w, top + plot_h, stroke="#555", width=1.2)

    legend_x = width - 300
    legend_y = 120
    for idx, cat in enumerate(categories):
        y = legend_y + idx * 24
        add_rect(parts, legend_x, y - 10, 16, 16, COLORS.get(cat, "#bbb"))
        add_text(parts, legend_x + 24, y + 3, cat, size=12)

    svg_close(parts, path)


def render_heatmap(
    rows: List[Dict[str, str]],
    categories: Sequence[str],
    title: str,
    subtitle: str,
    path: str,
) -> None:
    width, height = 1500, 900
    left, right, top, bottom = 260, 80, 120, 130
    plot_w = width - left - right
    plot_h = height - top - bottom
    years = list(range(1995, 2025))
    fields = [field for field in FIELD_ORDER if field != "Health sciences"]
    counts: Dict[str, Dict[int, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    for row in rows:
        field = row.get("nsf_broad_clean", "")
        year = to_int(row.get("grad_year"))
        if field not in fields or year not in years:
            continue
        counts[field][year][row.get("org_type_aggregate_v2", "")] += 1

    parts = svg_open(width, height)
    chart_title(parts, width, title, subtitle)
    cell_w = plot_w / len(years)
    cell_h = plot_h / len(fields)

    def value_to_color(value: float) -> str:
        # Cream to red.
        base = (247, 244, 239)
        high = (173, 47, 47)
        t = max(0.0, min(1.0, value))
        rgb = tuple(round(base[i] + (high[i] - base[i]) * t) for i in range(3))
        return "#" + "".join(f"{x:02x}" for x in rgb)

    for r_idx, field in enumerate(fields):
        y = top + r_idx * cell_h
        add_text(parts, left - 12, y + cell_h * 0.65, field, size=13, anchor="end")
        for c_idx, year in enumerate(years):
            x = left + c_idx * cell_w
            total = sum(counts[field][year].values())
            share = counts[field][year].get("Listed Company", 0) / total if total else 0.0
            add_rect(parts, x, y, cell_w, cell_h, value_to_color(share), stroke="#f0eadf")

    for c_idx, year in enumerate(years):
        if c_idx % 2 == 0:
            add_text(parts, left + c_idx * cell_w + cell_w / 2, top + plot_h + 22, str(year), size=11, anchor="middle", fill="#444")

    for tick, label in enumerate(["0%", "15%", "30%", "45%", "60%+"]):
        lx = width - 220 + tick * 28
        add_rect(parts, lx, height - 68, 28, 14, value_to_color(min(tick * 0.15, 0.60)))
        add_text(parts, lx + 14, height - 46, label, size=10, anchor="middle", fill="#444")
    add_text(parts, width - 220, height - 84, "Share entering listed companies", size=12)

    svg_close(parts, path)


def write_summary(rows: List[Dict[str, str]], diagnostics: Dict[str, object]) -> None:
    movement: Counter = diagnostics["movement"]  # type: ignore[assignment]
    old_counts: Counter = diagnostics["old_counts"]  # type: ignore[assignment]
    new_counts: Counter = diagnostics["new_counts"]  # type: ignore[assignment]
    changed_examples = diagnostics["changed_examples"]  # type: ignore[assignment]

    summary_path = os.path.join(OUT_DIR, "classification_summary.txt")
    total = len(rows)
    changed_total = sum(n for (old, new), n in movement.items() if old != new)

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("First job after PhD classification refresh (v2)\n")
        f.write("=============================================\n\n")
        f.write(f"Rows processed: {total}\n")
        f.write(f"Rows reassigned to a different org type: {changed_total} ({pct(changed_total, total)})\n\n")
        f.write("Original counts\n")
        for cat in ORG_ORDER + ["Listed Company - IPO Date Missing"]:
            if old_counts.get(cat):
                f.write(f"- {cat}: {old_counts[cat]}\n")
        f.write("\nUpdated counts\n")
        for cat in ORG_ORDER:
            if new_counts.get(cat):
                f.write(f"- {cat}: {new_counts[cat]}\n")
        f.write("\nLargest movements\n")
        for (old, new), n in movement.most_common():
            if old == new:
                continue
            f.write(f"- {old} -> {new}: {n}\n")
            examples = changed_examples.get((old, new), [])
            if examples:
                f.write(f"  Examples: {', '.join(examples[:4])}\n")

        f.write("\nRecommended meeting charts created\n")
        f.write("- chart_overall_sector_lines.svg\n")
        for field in FIELD_ORDER:
            if field_share_table(rows, "org_type_aggregate_v2").get(field):
                f.write(f"- chart_field_{slugify(field)}.svg\n")


def read_xlsx_shared_strings(zf) -> List[str]:
    import xml.etree.ElementTree as ET

    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    shared = []
    for si in root.findall("a:si", ns):
        texts = []
        for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"):
            texts.append(t.text or "")
        shared.append("".join(texts))
    return shared


def parse_sed_broad_counts(xlsx_path: str) -> Dict[int, Dict[str, int]]:
    import zipfile
    import xml.etree.ElementTree as ET

    if not os.path.exists(xlsx_path):
        return {}
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(xlsx_path) as zf:
        shared = read_xlsx_shared_strings(zf)
        ws = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    rows = ws.find("a:sheetData", ns)
    if rows is None:
        return {}

    header_years: Dict[str, int] = {}
    counts: Dict[int, Dict[str, int]] = defaultdict(dict)
    current_section = None
    for row in rows.findall("a:row", ns):
        values: Dict[str, str] = {}
        for c in row.findall("a:c", ns):
            ref = c.attrib.get("r", "")
            col = re.sub(r"\d+", "", ref)
            t = c.attrib.get("t")
            v = c.find("a:v", ns)
            val = v.text if v is not None else ""
            if t == "s" and val:
                val = shared[int(val)]
            values[col] = val
        if not values:
            continue
        label = values.get("A", "").strip()
        if label == "Field and 2021 Carnegie Classification":
            for col, val in values.items():
                if col == "A":
                    continue
                year = to_int(val)
                if year is not None:
                    header_years[col] = year
            continue
        if label in {"All doctorate recipients", "Science and engineering", "Non-science and engineering"}:
            current_section = label
            continue
        if current_section != "Science and engineering":
            continue
        if label.startswith("R1:") or label.startswith("R2:") or label in {"Doctoral/ professional universities", "Other universities"}:
            continue
        if label not in FIELD_ORDER:
            continue
        for col, year in header_years.items():
            val = values.get(col, "")
            num = to_int(val)
            if num is not None:
                counts[year][label] = num
    return counts


def parse_sed_taxonomy_schema(xlsx_path: str) -> Tuple[List[str], List[str]]:
    import zipfile
    import xml.etree.ElementTree as ET

    if not os.path.exists(xlsx_path):
        return list(DEFAULT_FIELD_ORDER), []

    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(xlsx_path) as zf:
        shared = read_xlsx_shared_strings(zf)
        ws = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))

    rows = ws.find("a:sheetData", ns)
    if rows is None:
        return list(DEFAULT_FIELD_ORDER), []

    broad_fields: List[str] = []
    major_fields: List[str] = []
    current_broad = None

    for row in rows.findall("a:row", ns):
        values: Dict[str, str] = {}
        for c in row.findall("a:c", ns):
            ref = c.attrib.get("r", "")
            col = re.sub(r"\d+", "", ref)
            t = c.attrib.get("t")
            v = c.find("a:v", ns)
            val = v.text if v is not None else ""
            if t == "s" and val:
                val = shared[int(val)]
            values[col] = val

        field = (values.get("A") or "").strip()
        level = (values.get("B") or "").strip()
        if not field or not level:
            continue

        if level == "Broad":
            if field == "Psychology":
                break
            if field not in {"Science and engineering", "Non-science and engineering"}:
                current_broad = schema_alias(field)
                broad_fields.append(current_broad)
            continue

        if level == "Major" and current_broad:
            major_fields.append(schema_alias(field))

    return broad_fields or list(DEFAULT_FIELD_ORDER), major_fields


def build_dashboard_payload(
    yearly_aggregate: Dict[int, Dict[str, int]],
    broad_year_counts: Dict[int, Dict[str, int]],
    sed_matched_counts: Dict[int, Dict[str, int]],
    sed_broad_counts: Dict[int, Dict[str, int]],
    broad_year_aggregate: Dict[str, Dict[int, Dict[str, int]]],
    major_year_aggregate: Dict[str, Dict[int, Dict[str, int]]],
    broad_top_orgs: Dict[str, List[Dict[str, object]]],
    major_top_orgs: Dict[str, List[Dict[str, object]]],
    broad_org_year_counts: Dict[str, Dict[int, Dict[str, int]]],
    major_org_year_counts: Dict[str, Dict[int, Dict[str, int]]],
    categories: Sequence[str],
) -> Dict[str, object]:
    years = sorted(yearly_aggregate)
    overall = []
    for cat in categories:
        series = []
        for year in years:
            total = sum(yearly_aggregate[year].values())
            share = yearly_aggregate[year].get(cat, 0) / total if total else 0.0
            series.append({"year": year, "share": round(share, 6)})
        overall.append({"name": cat, "label": display_label(cat), "color": COLORS.get(cat, "#333"), "values": series})

    broad_count_years = sorted(broad_year_counts)
    broad_count_series = []
    for field in FIELD_ORDER:
        series = []
        for year in broad_count_years:
            count = broad_year_counts[year].get(field, 0)
            series.append({"year": year, "value": count})
        if any(v["value"] for v in series):
            broad_count_series.append(
                {"name": field, "label": field, "color": COLORS.get(field, "#333"), "values": series}
            )

    sed_comparison_fields = []
    for field in FIELD_ORDER:
        matched_series = []
        sed_series = []
        years_union = sorted(set(sed_matched_counts) | set(sed_broad_counts))
        for year in years_union:
            if year < 2014 or year > 2020:
                continue
            matched_series.append({"year": year, "value": sed_matched_counts.get(year, {}).get(field, 0)})
            sed_series.append({"year": year, "value": sed_broad_counts.get(year, {}).get(field, 0)})
        if any(v["value"] for v in matched_series) or any(v["value"] for v in sed_series):
            sed_comparison_fields.append(
                {
                    "field": field,
                    "slug": slugify(field),
                    "series": [
                        {"name": "Matched file", "label": "Matched file", "color": "#1f4e79", "values": matched_series},
                        {"name": "SED", "label": "SED", "color": "#c43c39", "values": sed_series},
                    ],
                }
            )

    broad_fields = []
    for field in FIELD_ORDER:
        if field not in broad_year_aggregate:
            continue
        field_years = sorted(broad_year_aggregate[field])
        series_list = []
        for cat in categories:
            series = []
            for year in field_years:
                total = sum(broad_year_aggregate[field][year].values())
                share = broad_year_aggregate[field][year].get(cat, 0) / total if total else 0.0
                series.append({"year": year, "share": round(share, 6)})
            series_list.append({"name": cat, "label": display_label(cat), "color": COLORS.get(cat, "#333"), "values": series})
        broad_fields.append({
            "field": field,
            "slug": slugify(field),
            "series": series_list,
            "top_orgs": broad_top_orgs.get(field, []),
            "org_year_counts": broad_org_year_counts.get(field, {}),
        })

    major_fields = []
    for field in MAJOR_ORDER:
        year_data = major_year_aggregate.get(field)
        if not year_data:
            continue
        field_years = sorted(year_data)
        series_list = []
        for cat in categories:
            series = []
            for year in field_years:
                total = sum(year_data[year].values())
                share = year_data[year].get(cat, 0) / total if total else 0.0
                series.append({"year": year, "share": round(share, 6)})
            series_list.append({"name": cat, "label": display_label(cat), "color": COLORS.get(cat, "#333"), "values": series})
        major_fields.append({
            "field": field,
            "slug": slugify(field),
            "series": series_list,
            "top_orgs": major_top_orgs.get(field, []),
            "org_year_counts": major_org_year_counts.get(field, {}),
        })

    return {
        "categories": [{"name": cat, "label": display_label(cat), "color": COLORS.get(cat, "#333")} for cat in categories],
        "overall": {"title": "Where US STEM PhDs Go First: Sector Trends by Graduation Year", "series": overall},
        "overall_field_counts": {
            "title": "US STEM PhD Graduates by Graduation Year and NSF Broad Field",
            "series": broad_count_series,
        },
        "sed_comparison": {
            "title": "Matched File vs. Survey of Earned Doctorates by NSF Broad Field",
            "fields": sed_comparison_fields,
        },
        "broad_fields": broad_fields,
        "major_fields": major_fields,
    }


def write_dashboard_html(payload: Dict[str, object]) -> None:
    dashboard_path = os.path.join(OUT_DIR, "dashboard.html")
    data_json = json.dumps(payload)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>First Jobs After PhD Dashboard</title>
  <style>
    :root {{
      --bg: #f7f4ef;
      --card: #fffdf8;
      --ink: #222;
      --muted: #666;
      --grid: #ddd7ca;
      --border: #d8d2c4;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background: var(--bg);
      color: var(--ink);
    }}
    .wrap {{
      max-width: 1680px;
      margin: 0 auto;
      padding: 24px 24px 48px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 32px;
    }}
    p.sub {{
      margin: 0 0 24px;
      color: var(--muted);
      font-size: 15px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 18px 18px 22px;
      margin-bottom: 24px;
      box-shadow: 0 1px 0 rgba(0,0,0,0.03);
    }}
    .controls {{
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      align-items: end;
      margin-bottom: 18px;
    }}
    .control {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 280px;
    }}
    .range-control {{
      min-width: 220px;
    }}
    .range-row {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .mini-control {{
      margin: 8px 0 12px;
      max-width: 420px;
    }}
    label {{
      font-size: 13px;
      color: var(--muted);
    }}
    select {{
      font: 15px Georgia, "Times New Roman", serif;
      padding: 8px 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: white;
      color: var(--ink);
    }}
    input[type="range"] {{
      width: 100%;
    }}
    .range-value {{
      font-size: 13px;
      color: var(--muted);
      min-width: 42px;
      text-align: right;
    }}
    .title {{
      font-size: 24px;
      font-weight: 700;
      margin-bottom: 4px;
    }}
    .subtitle {{
      color: var(--muted);
      font-size: 14px;
      margin-bottom: 14px;
    }}
    .note {{
      color: #7a7a7a;
      font-size: 12px;
      line-height: 1.45;
      margin-top: 12px;
    }}
    .chart-box {{
      position: relative;
    }}
    canvas {{
      width: 100%;
      height: 520px;
      display: block;
    }}
    .tooltip {{
      position: absolute;
      pointer-events: none;
      background: rgba(34,34,34,0.94);
      color: white;
      padding: 8px 10px;
      border-radius: 6px;
      font-size: 12px;
      line-height: 1.35;
      opacity: 0;
      transform: translate(10px, -10px);
      white-space: nowrap;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 24px;
    }}
    table.rank {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
      margin-top: 8px;
    }}
    table.rank th, table.rank td {{
      padding: 8px 10px;
      border-top: 1px solid var(--border);
      vertical-align: top;
    }}
    table.rank th {{
      text-align: left;
      color: var(--muted);
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>First Jobs After PhD</h1>
    <p class="sub">Interactive dashboard of first-job outcomes for U.S. STEM PhDs. Hover over points to see year and share.</p>
    <div class="card">
      <div class="controls">
        <div class="control">
          <label for="view-select">View</label>
          <select id="view-select">
            <option value="overall">Overall sample</option>
            <option value="broad">NSF broad field</option>
            <option value="major">NSF major field</option>
            <option value="sed">SED comparison</option>
          </select>
        </div>
        <div class="control">
          <label for="field-select">Field</label>
          <select id="field-select"></select>
        </div>
        <div class="control range-control">
          <label for="year-start">Start year</label>
          <div class="range-row">
            <input id="year-start" type="range">
            <span id="year-start-label" class="range-value"></span>
          </div>
        </div>
        <div class="control range-control">
          <label for="year-end">End year</label>
          <div class="range-row">
            <input id="year-end" type="range">
            <span id="year-end-label" class="range-value"></span>
          </div>
        </div>
      </div>
      <div id="chart-host"></div>
    </div>
  </div>
  <script>
    const DATA = {data_json};

    function renderChart(container, title, subtitle, series, opts = {{}}) {{
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `<div class="title">${{title}}</div><div class="subtitle">${{subtitle}}</div>`;
      if (opts.extraControl) {{
        card.appendChild(opts.extraControl);
      }}
      const box = document.createElement('div');
      box.className = 'chart-box';
      const canvas = document.createElement('canvas');
      const tooltip = document.createElement('div');
      tooltip.className = 'tooltip';
      box.appendChild(canvas);
      box.appendChild(tooltip);
      card.appendChild(box);
      container.appendChild(card);

      const dpr = window.devicePixelRatio || 1;
      const width = 1500;
      const height = 520;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.height = height + 'px';
      const ctx = canvas.getContext('2d');
      ctx.scale(dpr, dpr);

      const margin = {{top: 18, right: 350, bottom: 52, left: 88}};
      const plotW = width - margin.left - margin.right;
      const plotH = height - margin.top - margin.bottom;
      const yearRange = opts.yearRange || null;
      const filteredSeries = series.map((s) => ({{
        ...s,
        values: s.values.filter((v) => !yearRange || (v.year >= yearRange[0] && v.year <= yearRange[1]))
      }}));
      const years = [...new Set(filteredSeries.flatMap((s) => s.values.map((v) => v.year)))].sort((a, b) => a - b);
      if (!years.length) {{
        const empty = document.createElement('div');
        empty.style.color = '#666';
        empty.style.padding = '12px 0 4px';
        empty.textContent = 'No data in the selected year range.';
        card.appendChild(empty);
        container.appendChild(card);
        return;
      }}
      const mode = opts.mode || 'share';
      const yLabel = opts.yLabel || 'Share of first jobs';
      const rawMax = mode === 'count'
        ? Math.max(...filteredSeries.flatMap(s => s.values.map(v => v.value || 0)))
        : 0.8;
      const maxY = mode === 'count'
        ? Math.max(1000, Math.ceil(rawMax / 1000) * 1000)
        : 0.8;
      const minY = 0;
      const hoverPoints = [];

      function xPos(year) {{
        return margin.left + ((year - years[0]) / Math.max(years[years.length - 1] - years[0], 1)) * plotW;
      }}
      function yPos(share) {{
        return margin.top + plotH - ((share - minY) / (maxY - minY)) * plotH;
      }}

      ctx.fillStyle = '#fffdf8';
      ctx.fillRect(0, 0, width, height);

      ctx.strokeStyle = '#ddd7ca';
      ctx.fillStyle = '#666';
      ctx.font = '12px Georgia';
      const tickStep = mode === 'count' ? Math.max(1000, Math.round(maxY / 5 / 1000) * 1000) : 0.1;
      for (let tick = 0; tick <= maxY + 1e-9; tick += tickStep) {{
        const y = yPos(tick);
        ctx.beginPath();
        ctx.moveTo(margin.left, y);
        ctx.lineTo(margin.left + plotW, y);
        ctx.stroke();
        ctx.textAlign = 'right';
        ctx.fillText(mode === 'count' ? tick.toLocaleString() : Math.round(tick * 100) + '%', margin.left - 10, y + 4);
      }}

      ctx.strokeStyle = '#555';
      ctx.beginPath();
      ctx.moveTo(margin.left, margin.top);
      ctx.lineTo(margin.left, margin.top + plotH);
      ctx.lineTo(margin.left + plotW, margin.top + plotH);
      ctx.stroke();

      for (const year of years) {{
        if (year % 2 === 0) {{
          ctx.textAlign = 'center';
          ctx.fillStyle = '#666';
          ctx.fillText(String(year), xPos(year), margin.top + plotH + 24);
        }}
      }}

      ctx.save();
      ctx.translate(24, margin.top + plotH / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center';
      ctx.fillStyle = '#222';
      ctx.font = '14px Georgia';
      ctx.fillText(yLabel, 0, 0);
      ctx.restore();

      ctx.textAlign = 'center';
      ctx.fillText('PhD graduation year', margin.left + plotW / 2, height - 14);

      filteredSeries.forEach((s) => {{
        ctx.strokeStyle = s.color;
        ctx.lineWidth = 3;
        ctx.beginPath();
        s.values.forEach((v, i) => {{
          const x = xPos(v.year);
          const val = mode === 'count' ? (v.value || 0) : v.share;
          const y = yPos(val);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
          hoverPoints.push({{x, y, color: s.color, label: s.label, year: v.year, share: v.share, value: v.value}});
        }});
        ctx.stroke();
        s.values.forEach((v) => {{
          const x = xPos(v.year);
          const val = mode === 'count' ? (v.value || 0) : v.share;
          const y = yPos(val);
          ctx.fillStyle = s.color;
          ctx.beginPath();
          ctx.arc(x, y, 3.5, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = '#fff';
          ctx.lineWidth = 1.2;
          ctx.stroke();
        }});
      }});

      const legendX = margin.left + plotW + 30;
      const legendY = margin.top + 10;
      ctx.textAlign = 'left';
      ctx.font = '12px Georgia';
      filteredSeries.forEach((s, idx) => {{
        const y = legendY + idx * 24;
        ctx.fillStyle = s.color;
        ctx.fillRect(legendX, y - 10, 16, 16);
        ctx.fillStyle = '#222';
        ctx.fillText(s.label, legendX + 24, y + 3);
      }});

      canvas.addEventListener('mousemove', (e) => {{
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        let best = null;
        let bestDist = 12;
        for (const p of hoverPoints) {{
          const d = Math.hypot(mx - p.x, my - p.y);
          if (d < bestDist) {{
            bestDist = d;
            best = p;
          }}
        }}
        if (best) {{
          tooltip.style.opacity = '1';
          tooltip.style.left = (best.x + 12) + 'px';
          tooltip.style.top = (best.y - 12) + 'px';
          tooltip.innerHTML = mode === 'count'
            ? `<strong>${{best.label}}</strong><br>Graduation year: ${{best.year}}<br>Graduates: ${{(best.value || 0).toLocaleString()}}`
            : `<strong>${{best.label}}</strong><br>Graduation year: ${{best.year}}<br>Share: ${{(best.share * 100).toFixed(1)}}%`;
        }} else {{
          tooltip.style.opacity = '0';
        }}
      }});
      canvas.addEventListener('mouseleave', () => {{
        tooltip.style.opacity = '0';
      }});

      if (opts.note) {{
        const note = document.createElement('div');
        note.className = 'note';
        note.textContent = opts.note;
        card.appendChild(note);
      }}
    }}

    function topOrgsForRange(orgYearCounts, yearRange, topN = 10) {{
      const totals = new Map();
      const [startYear, endYear] = yearRange;
      Object.entries(orgYearCounts || {{}}).forEach(([yearText, orgCounts]) => {{
        const year = Number(yearText);
        if (year < startYear || year > endYear) return;
        Object.entries(orgCounts || {{}}).forEach(([org, count]) => {{
          totals.set(org, (totals.get(org) || 0) + Number(count || 0));
        }});
      }});
      return [...totals.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .slice(0, topN)
        .map(([name, count]) => ({{ name, count }}));
    }}

    function renderTopOrgs(container, fieldName, orgYearCounts, yearRange) {{
      const items = topOrgsForRange(orgYearCounts, yearRange, 10);
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `<div class="title">Top 10 Organizations: ${{fieldName}}</div><div class="subtitle">Largest organizations in the matched first-job file for the selected field within the selected year window. This table updates with the sliders.</div>`;
      const table = document.createElement('table');
      table.className = 'rank';
      table.innerHTML = '<thead><tr><th style="width:50px;">Rank</th><th>Organization</th><th style="width:90px;">Count</th></tr></thead>';
      const tbody = document.createElement('tbody');
      if (!items.length) {{
        const tr = document.createElement('tr');
        tr.innerHTML = '<td colspan="3">No organizations in the selected year range.</td>';
        tbody.appendChild(tr);
      }} else {{
        items.forEach((item, idx) => {{
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${{idx + 1}}</td><td>${{item.name}}</td><td>${{Number(item.count).toLocaleString()}}</td>`;
          tbody.appendChild(tr);
        }});
      }}
      table.appendChild(tbody);
      card.appendChild(table);
      const note = document.createElement('div');
      note.className = 'note';
      note.textContent = 'Note: Organization names use the best available employer identifier in this priority order: Revelio primary name, Revelio company, ultimate parent name, company_raw, then company_cleaned. Counts are based on one retained observation per rev_user_id within the selected year window.';
      card.appendChild(note);
      container.appendChild(card);
    }}

    const viewSelect = document.getElementById('view-select');
    const fieldSelect = document.getElementById('field-select');
    const yearStart = document.getElementById('year-start');
    const yearEnd = document.getElementById('year-end');
    const yearStartLabel = document.getElementById('year-start-label');
    const yearEndLabel = document.getElementById('year-end-label');
    const host = document.getElementById('chart-host');
    const allYears = [
      ...new Set([
        ...DATA.overall.series.flatMap((s) => s.values.map((v) => v.year)),
        ...DATA.overall_field_counts.series.flatMap((s) => s.values.map((v) => v.year)),
        ...DATA.broad_fields.flatMap((f) => f.series.flatMap((s) => s.values.map((v) => v.year))),
        ...DATA.major_fields.flatMap((f) => f.series.flatMap((s) => s.values.map((v) => v.year))),
        ...DATA.overall_sed_comparison.fields.flatMap((f) => f.series.flatMap((s) => s.values.map((v) => v.year)))
      ])
    ].sort((a, b) => a - b);
    const minYear = allYears[0];
    const maxYear = allYears[allYears.length - 1];
    yearStart.min = minYear;
    yearStart.max = maxYear;
    yearEnd.min = minYear;
    yearEnd.max = maxYear;
    yearStart.value = minYear;
    yearEnd.value = maxYear;

    function syncYearLabels() {{
      yearStartLabel.textContent = yearStart.value;
      yearEndLabel.textContent = yearEnd.value;
    }}

    function currentYearRange() {{
      let start = Number(yearStart.value);
      let end = Number(yearEnd.value);
      if (start > end) [start, end] = [end, start];
      return [start, end];
    }}

    function currentCollection() {{
      if (viewSelect.value === 'broad') return DATA.broad_fields;
      if (viewSelect.value === 'major') return DATA.major_fields;
      if (viewSelect.value === 'sed') return DATA.sed_comparison.fields;
      return [];
    }}

    function refreshFieldOptions() {{
      fieldSelect.innerHTML = '';
      if (viewSelect.value === 'overall') {{
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'Overall sample';
        fieldSelect.appendChild(opt);
        fieldSelect.disabled = true;
        return;
      }}
      fieldSelect.disabled = false;
      currentCollection().forEach((item) => {{
        const opt = document.createElement('option');
        opt.value = item.slug;
        opt.textContent = item.field;
        fieldSelect.appendChild(opt);
      }});
    }}

    function renderCurrent() {{
      host.innerHTML = '';
      if (viewSelect.value === 'overall') {{
        renderChart(
          host,
          DATA.overall.title,
          'Shares of first observed post-PhD jobs after deduplicating to one retained observation per rev_user_id. Government combines agencies and labs; academia is universities only.',
          DATA.overall.series,
          {{ mode: 'share', yLabel: 'Share of first jobs', yearRange: currentYearRange(), note: 'Note: The main job-outcome views are person-level. When the same rev_user_id appears multiple times, the dashboard keeps one retained observation using a deterministic preference for stronger employer and classification information.' }}
        );
        renderChart(
          host,
          DATA.overall_field_counts.title,
          'Counts by graduation year across NSF broad fields after deduplicating to one retained observation per rev_user_id.',
          DATA.overall_field_counts.series,
          {{ mode: 'count', yLabel: 'Graduates in matched file', yearRange: currentYearRange(), note: 'Note: These counts are from the matched first-job file, not the full SED universe. Broad fields shown here are the SED taxonomy broad fields that occur above Psychology in the official schema file.' }}
        );
        return;
      }}
      if (viewSelect.value === 'sed') {{
        const selectedSed = DATA.sed_comparison.fields.find((item) => item.slug === fieldSelect.value) || DATA.sed_comparison.fields[0];
        if (!selectedSed) return;
        renderChart(
          host,
          `${{DATA.sed_comparison.title}}: ${{selectedSed.field}}`,
          'Solid blue line is the matched file counted by distinct pq_row_id; red line is the official NCSES SED count. This comparison is restricted to 2014–2020.',
          selectedSed.series,
          {{ mode: 'count', yLabel: 'Graduates', yearRange: currentYearRange(), note: 'Note: Unlike the main dashboard views, the matched-file side of this SED comparison uses distinct pq_row_id rather than rev_user_id. The official SED series currently comes from NCSES Table 1-2 and is shown only for 2014–2020.' }}
        );
        return;
      }}
      const selected = currentCollection().find((item) => item.slug === fieldSelect.value) || currentCollection()[0];
      if (!selected) return;
      const fieldType = viewSelect.value === 'broad' ? 'NSF broad field' : 'NSF major field';
      renderChart(
        host,
        `First-Job Sector Trends: ${{selected.field}}`,
        `Shares of first observed post-PhD jobs by graduation cohort within this ${{fieldType}}, using one retained observation per rev_user_id.`,
        selected.series,
        {{ mode: 'share', yLabel: 'Share of first jobs', yearRange: currentYearRange(), note: viewSelect.value === 'broad' ? 'Note: Broad fields follow the official SED taxonomy and include only fields that occur above Psychology in the schema file nsf25349-taba-004.xlsx. The source dataset itself is not altered; this is a dashboard inclusion rule.' : 'Note: Major fields follow the official SED taxonomy and include only majors nested under broad fields that occur above Psychology in the schema file nsf25349-taba-004.xlsx. This excludes Psychology and lower fields, including geography-related fields outside the retained schema block.' }}
      );
      renderTopOrgs(host, selected.field, selected.org_year_counts || {{}}, currentYearRange());
    }}

    viewSelect.addEventListener('change', () => {{
      refreshFieldOptions();
      renderCurrent();
    }});
    fieldSelect.addEventListener('change', renderCurrent);
    yearStart.addEventListener('input', () => {{
      if (Number(yearStart.value) > Number(yearEnd.value)) yearEnd.value = yearStart.value;
      syncYearLabels();
      renderCurrent();
    }});
    yearEnd.addEventListener('input', () => {{
      if (Number(yearEnd.value) < Number(yearStart.value)) yearStart.value = yearEnd.value;
      syncYearLabels();
      renderCurrent();
    }});

    syncYearLabels();
    refreshFieldOptions();
    renderCurrent();
  </script>
</body>
</html>
"""
    with open(dashboard_path, "w", encoding="utf-8") as f:
        f.write(html)


def main() -> None:
    global OVERRIDES, FIELD_ORDER, MAJOR_ORDER
    OVERRIDES = load_overrides()
    FIELD_ORDER, MAJOR_ORDER = parse_sed_taxonomy_schema(SED_TAXONOMY_XLSX)
    rows, diagnostics = load_and_recode()
    person_rows = dedupe_rows_by_rev_user_id(rows)
    yearly_aggregate = yearly_share_table(person_rows, "org_type_aggregate_v2")
    broad_year_counts = yearly_count_table(person_rows, "nsf_broad_clean", allowed_groups=FIELD_ORDER)
    sed_broad_counts = parse_sed_broad_counts(SED_BROAD_XLSX)
    sed_matched_counts = yearly_distinct_id_count_table(rows, "nsf_broad_clean", "pq_row_id", allowed_groups=FIELD_ORDER)
    field_year_aggregate = field_year_share_table(person_rows, "org_type_aggregate_v2")
    major_year_aggregate = group_year_share_table(person_rows, "nsf_major", "org_type_aggregate_v2")
    broad_top_orgs = top_orgs_by_group(person_rows, "nsf_broad_clean", exclude_values=["Other / Small Fields"])
    major_top_orgs = top_orgs_by_group(person_rows, "nsf_major")
    broad_org_year_counts = org_year_counts_by_group(person_rows, "nsf_broad_clean", exclude_values=["Other / Small Fields"])
    major_org_year_counts = org_year_counts_by_group(person_rows, "nsf_major")

    render_line_chart(
        yearly_aggregate,
        [
            "Academia",
            "Research Institute / Nonprofit",
            "Government",
            "Listed Company",
            "Startup / VC-backed Private Firm",
            "Business (Unclassified)",
        ],
        "Where US STEM PhDs Go First: Sector Trends by Graduation Year",
        "Shares of first observed post-PhD jobs. Government combines agencies and labs; academia is universities only.",
        os.path.join(OUT_DIR, "chart_overall_sector_lines.svg"),
        y_max=0.70,
        show_line_end_labels=False,
    )

    field_categories = [
        "Academia",
        "Research Institute / Nonprofit",
        "Hospital / Health",
        "Government",
        "Listed Company",
        "Startup / VC-backed Private Firm",
        "Business (Unclassified)",
    ]
    for field in FIELD_ORDER:
        if field not in field_year_aggregate:
            continue
        render_field_line_chart(
            field,
            field_year_aggregate[field],
            field_categories,
            f"First-Job Sector Trends: {field}",
            "Shares of first observed post-PhD jobs by graduation cohort within this NSF broad field.",
            os.path.join(OUT_DIR, f"chart_field_{slugify(field)}.svg"),
        )

    write_summary(rows, diagnostics)
    write_dashboard_html(
        build_dashboard_payload(
            yearly_aggregate,
            broad_year_counts,
            sed_matched_counts,
            sed_broad_counts,
            field_year_aggregate,
            major_year_aggregate,
            broad_top_orgs,
            major_top_orgs,
            broad_org_year_counts,
            major_org_year_counts,
            field_categories,
        )
    )


if __name__ == "__main__":
    main()
