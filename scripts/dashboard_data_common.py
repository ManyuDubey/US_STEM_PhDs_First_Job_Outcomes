#!/usr/bin/env python3
"""Shared helpers for the PhD outcomes dashboard pages."""

from __future__ import annotations

import csv
import html
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, Optional


ROOT = Path(__file__).resolve().parents[1]
CODEX_DATA = ROOT / "codex_data"
OUTPUT_DIR = ROOT / "outputs" / "first_job_graphs"
DOCS_DIR = ROOT / "docs"
FIRST_JOB_INPUT = CODEX_DATA / "post_phd_first_job_dashboard_input.csv"
DEG_INFO = ROOT / "deg_info.csv"


EMPTY_VALUES = {"", "empty", "none", "null", "nan", "-"}

PHD_RE = re.compile(r"\b(ph\.?\s*d\.?|doctor of philosophy)\b", re.IGNORECASE)
PROFESSIONAL_DOCTOR_RE = re.compile(
    r"\b("
    r"m\.?\s*d\.?|doctor of medicine|j\.?\s*d\.?|juris doctor|doctor of law|"
    r"d\.?\s*v\.?\s*m\.?|doctor of veterinary|doctor of nursing|dnp"
    r")\b",
    re.IGNORECASE,
)
BACHELOR_RE = re.compile(
    r"\b("
    r"bachelor|bachelor'?s|bachelor.s|"
    r"b\.?\s*s\.?|bsc|b\.?\s*sc\.?|"
    r"b\.?\s*a\.?|"
    r"beng|b\.?\s*eng\.?|btech|b\.?\s*tech\.?|"
    r"b\.?\s*e\.?|b\.?\s*com\.?|licen[cs]e|undergraduate"
    r")\b",
    re.IGNORECASE,
)
SAFE_BACHELOR_ABBREV_RE = re.compile(
    r"^(a\.?b\.?|s\.?b\.?|scb|bse|bsee|bsme|bsce|bsie|bsche|bche|bme|"
    r"bsae|bsa|basc|bas|bsci|b\.sci\.?|hbsc|beng|b\.eng\.?|btech|"
    r"b\.tech\.?|b\.arch\.?|bsph|bcom|b\.com\.?|m\.?b\.?b\.?s\.?)$",
    re.IGNORECASE,
)
SAFE_BACHELOR_WORD_RE = re.compile(
    r"\b("
    r"bachelor|bacheloru2019s|bachelorâ|baccalaureate|bacharelado|"
    r"bachalor|bachlor|bachelar|batchelor|undergrad|licence"
    r")\b",
    re.IGNORECASE,
)
SAFE_ENGINEERING_EQUIV_RE = re.compile(
    r"\b(diplom[ -]ingenieur|diplome d['’]ingenieur|engineering diploma|diploma engineer)\b",
    re.IGNORECASE,
)
NON_BACHELOR_RE = re.compile(
    r"\b(master|mba|m\.?\s*s\.?|m\.?\s*a\.?|ph\.?\s*d\.?|doctor|jd|j\.?\s*d\.?|"
    r"md|m\.?\s*d\.?|high school|certificate|associate)\b",
    re.IGNORECASE,
)
SAFE_BACHELOR_EXCLUDE_RE = re.compile(
    r"\b("
    r"master|mba|executive mba|ph\.?\s*d|doctor|high school|school diploma|"
    r"certificate|post graduate|habilitation|diplomate|abitur|m\.?\s*d\.?|"
    r"j\.?\s*d\.?|surgery|medicine|mbbs"
    r")\b",
    re.IGNORECASE,
)


def clean(value: object) -> str:
    text = html.unescape(str(value or "")).strip()
    return "" if text.lower() in EMPTY_VALUES else text


def norm_id(value: object) -> str:
    text = clean(value)
    if text.endswith(".0"):
        return text[:-2]
    return text


def to_int(value: object) -> Optional[int]:
    text = clean(value).replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def norm_label(value: object) -> str:
    text = clean(value).lower()
    text = text.replace("&amp;", "&")
    text = re.sub(r"[^a-z0-9&]+", " ", text)
    text = text.replace("&", " and ")
    return re.sub(r"\s+", " ", text).strip()


def norm_institution(value: object) -> str:
    text = norm_label(value)
    replacements = {
        " u ": " university ",
        " univ ": " university ",
        " c ": " college ",
        " coll ": " college ",
        " s ": " school ",
        " inst ": " institute ",
        " tech ": " technology ",
        " med ": " medical ",
    }
    text = f" {text} "
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\bthe\b", " ", text)
    text = re.sub(r"\bof\b", " ", text)
    text = re.sub(r"\bat\b", " ", text)
    text = re.sub(r"\bin\b", " ", text)
    text = re.sub(r"\bmain campus\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def institution_variants(value: object) -> list[str]:
    base = norm_institution(value)
    variants = {base}
    campus_suffixes = [
        "ann arbor",
        "twin cities",
        "columbus",
        "madison",
        "berkeley",
        "seattle",
        "los angeles",
        "urbana champaign",
        "austin",
        "west lafayette",
        "pittsburgh",
        "college park",
        "san diego",
        "davis",
        "irvine",
        "santa barbara",
        "chapel hill",
        "raleigh",
    ]
    for suffix in campus_suffixes:
        if base.endswith(" " + suffix):
            variants.add(base[: -len(suffix)].strip())
    return [v for v in variants if v]


def country_from_degree_row(row: Dict[str, str]) -> tuple[str, str]:
    country = clean(row.get("university_country"))
    if country:
        return normalize_country(country), "university_country"

    location = clean(row.get("university_location"))
    if location and "," in location:
        guessed = location.split(",")[-1].strip()
        if guessed:
            return normalize_country(guessed), "university_location_tail"
    return "", "missing"


def build_unique_institution_country_map(
    users: Dict[str, Dict[str, str]] | None = None,
    min_evidence: int = 5,
) -> Dict[str, str]:
    wanted_users = set(users or {})
    countries: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    with DEG_INFO.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if wanted_users and norm_id(row.get("rev_user_id")) not in wanted_users:
                continue
            country = clean(row.get("university_country"))
            if not country:
                continue
            country = normalize_country(country)
            for field in ["university_name", "university_raw", "ultimate_parent_school_name"]:
                inst = clean(row.get(field))
                if inst:
                    countries[inst][country] += 1

    out: Dict[str, str] = {}
    for inst, counter in countries.items():
        if len(counter) == 1 and sum(counter.values()) >= min_evidence:
            out[inst] = next(iter(counter))
    return out


def infer_country_from_degree_row(
    row: Dict[str, str],
    institution_country_map: Dict[str, str],
) -> tuple[str, str]:
    country, source = country_from_degree_row(row)
    if country:
        return country, source
    for field in ["university_name", "university_raw", "ultimate_parent_school_name"]:
        inst = clean(row.get(field))
        if inst and inst in institution_country_map:
            return institution_country_map[inst], "unique_institution_country"
    return "", "missing"


def normalize_country(country: str) -> str:
    aliases = {
        "United States of America": "United States",
        "USA": "United States",
        "U.S.A.": "United States",
        "UK": "United Kingdom",
        "Korea, South": "South Korea",
        "Republic of Korea": "South Korea",
        "Iran, Islamic Republic of": "Iran",
        "Russian Federation": "Russia",
    }
    return aliases.get(country, country)


def load_first_job_users(path: Path = FIRST_JOB_INPUT) -> Dict[str, Dict[str, str]]:
    users: Dict[str, Dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_id = norm_id(row.get("rev_user_id"))
            if not user_id:
                continue
            users[user_id] = {
                "goid": norm_id(row.get("goid")),
                "rev_user_id": user_id,
                "grad_year": clean(row.get("grad_year")),
                "nsf_primary": clean(row.get("nsf_primary")),
                "nsf_major": clean(row.get("nsf_major")),
                "nsf_broad": clean(row.get("nsf_broad")),
            }
    return users


def is_phd_degree(row: Dict[str, str]) -> bool:
    raw = clean(row.get("degree_raw"))
    degree = clean(row.get("degree")).lower()
    if PHD_RE.search(raw):
        return True
    return degree == "doctor" and not PROFESSIONAL_DOCTOR_RE.search(raw)


def is_bachelor_degree(row: Dict[str, str]) -> bool:
    return bool(bachelor_degree_signal(row))


def bachelor_degree_signal(row: Dict[str, str]) -> str:
    degree = clean(row.get("degree")).lower()
    raw = clean(row.get("degree_raw"))
    if degree == "bachelor":
        return "degree_bachelor"
    if BACHELOR_RE.search(raw):
        return "revelio_bachelor_pattern"
    if re.search(r"\b(m\.?b\.?b\.?s\.?|bachelor of medicine)\b", raw, re.IGNORECASE):
        return "safe_medical_bachelor_equivalent"
    if SAFE_BACHELOR_EXCLUDE_RE.search(raw):
        return ""
    if SAFE_BACHELOR_ABBREV_RE.match(raw):
        return "safe_bachelor_abbreviation"
    if SAFE_BACHELOR_WORD_RE.search(raw):
        return "safe_bachelor_word_or_typo"
    if SAFE_ENGINEERING_EQUIV_RE.search(raw):
        return "safe_engineering_bachelor_equivalent"
    return ""


def degree_university(row: Dict[str, str]) -> str:
    return (
        clean(row.get("university_raw"))
        or clean(row.get("university_name"))
        or clean(row.get("ultimate_parent_school_name"))
    )


def index_degree_rows(users: Dict[str, Dict[str, str]]) -> tuple[dict[str, list[Dict[str, str]]], dict[str, list[Dict[str, str]]]]:
    by_user: dict[str, list[Dict[str, str]]] = defaultdict(list)
    by_goid: dict[str, list[Dict[str, str]]] = defaultdict(list)
    wanted_users = set(users)
    wanted_goids = {info["goid"] for info in users.values() if info.get("goid")}
    with DEG_INFO.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_id = norm_id(row.get("rev_user_id"))
            goid = norm_id(row.get("goid"))
            if user_id in wanted_users:
                by_user[user_id].append(row)
            if goid in wanted_goids:
                by_goid[goid].append(row)
    return by_user, by_goid


def choose_phd_row(
    user_info: Dict[str, str],
    by_user: dict[str, list[Dict[str, str]]],
    by_goid: dict[str, list[Dict[str, str]]],
) -> tuple[Dict[str, str] | None, str]:
    goid = user_info.get("goid", "")
    user_id = user_info.get("rev_user_id", "")
    candidates = [row for row in by_goid.get(goid, []) if is_phd_degree(row)]
    source = "goid"
    if not candidates:
        candidates = [row for row in by_user.get(user_id, []) if is_phd_degree(row)]
        source = "rev_user_id"
    if not candidates:
        return None, "missing"

    grad_year = to_int(user_info.get("grad_year"))

    def score(row: Dict[str, str]) -> tuple[int, int, int, int, str]:
        raw = clean(row.get("degree_raw"))
        end_year = to_int(row.get("edu_end_year"))
        phd_score = 0 if PHD_RE.search(raw) else 1
        distance = abs((end_year or 9999) - grad_year) if grad_year else 9999
        missing_end = 1 if end_year is None else 0
        after_gap = max(0, (end_year or 0) - (grad_year or 9999)) if grad_year else 0
        return (phd_score, distance, after_gap, missing_end, degree_university(row).lower())

    return min(candidates, key=score), source


def choose_bachelor_row(
    user_info: Dict[str, str],
    by_user: dict[str, list[Dict[str, str]]],
    by_goid: dict[str, list[Dict[str, str]]],
    institution_country_map: Dict[str, str] | None = None,
) -> tuple[Dict[str, str] | None, str]:
    institution_country_map = institution_country_map or {}
    goid = user_info.get("goid", "")
    user_id = user_info.get("rev_user_id", "")
    candidates = [row for row in by_goid.get(goid, []) if is_bachelor_degree(row)]
    source = "goid"
    if not candidates:
        candidates = [row for row in by_user.get(user_id, []) if is_bachelor_degree(row)]
        source = "rev_user_id"
    if not candidates:
        return None, "missing"

    grad_year = to_int(user_info.get("grad_year"))

    def score(row: Dict[str, str]) -> tuple[int, int, int, int, str]:
        degree = clean(row.get("degree")).lower()
        raw = clean(row.get("degree_raw"))
        end_year = to_int(row.get("edu_end_year"))
        country, _ = infer_country_from_degree_row(row, institution_country_map)
        signal = bachelor_degree_signal(row)
        after_phd = 1 if grad_year and end_year and end_year > grad_year else 0
        missing_end = 1 if end_year is None else 0
        explicit = 0 if degree == "bachelor" else 1
        contaminated = 1 if NON_BACHELOR_RE.search(raw) and degree != "bachelor" else 0
        signal_rank = {
            "degree_bachelor": 0,
            "revelio_bachelor_pattern": 1,
            "safe_bachelor_abbreviation": 2,
            "safe_bachelor_word_or_typo": 3,
            "safe_engineering_bachelor_equivalent": 4,
        }.get(signal, 9)
        year = end_year if end_year is not None else 9999
        missing_country = 1 if not country else 0
        return (
            after_phd,
            contaminated,
            explicit,
            signal_rank,
            missing_country,
            missing_end,
            year,
            degree_university(row).lower(),
        )

    return min(candidates, key=score), source


def html_shell(title: str, subtitle: str, body: str, data_script: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f7f4ef;
      --card: #fffdf8;
      --ink: #222;
      --muted: #666;
      --grid: #ddd7ca;
      --border: #d8d2c4;
      --blue: #1f4e79;
      --red: #c43c39;
      --green: #5b8e7d;
    }}
    body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; background: var(--bg); color: var(--ink); }}
    .wrap {{ max-width: 1500px; margin: 0 auto; padding: 24px 24px 48px; }}
    nav {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 0 0 18px; font-size: 14px; }}
    nav a {{ color: var(--blue); text-decoration: none; border-bottom: 1px solid transparent; }}
    nav a:hover {{ border-color: var(--blue); }}
    h1 {{ margin: 0 0 6px; font-size: 32px; }}
    p.sub {{ margin: 0 0 24px; color: var(--muted); font-size: 15px; }}
    .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 18px; margin-bottom: 24px; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
    .stat {{ border-top: 3px solid var(--blue); padding-top: 8px; }}
    .stat .value {{ font-size: 26px; font-weight: 700; }}
    .stat .label {{ color: var(--muted); font-size: 13px; }}
    .controls {{ display: flex; gap: 14px; flex-wrap: wrap; align-items: end; margin: 0 0 16px; }}
    .control {{ display: flex; flex-direction: column; gap: 6px; min-width: 240px; }}
    .year-controls {{ display: flex; gap: 14px; flex: 1 1 520px; min-width: min(520px, 100%); }}
    .year-control {{ flex: 1 1 0; min-width: 0; }}
    .year-control input[type="range"] {{ box-sizing: border-box; width: 100%; }}
    .title {{ font-size: 24px; font-weight: 700; margin-bottom: 4px; }}
    .subtitle {{ color: var(--muted); font-size: 14px; margin-bottom: 14px; }}
    .range-value {{ color: var(--muted); font-size: 13px; }}
    .chart-box {{ position: relative; }}
    label {{ color: var(--muted); font-size: 13px; }}
    select, input {{ font: 15px Georgia, "Times New Roman", serif; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; background: white; color: var(--ink); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-top: 1px solid var(--border); padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; }}
    .chart {{ width: 100%; height: 460px; display: block; }}
    .tooltip {{ position: absolute; pointer-events: none; background: rgba(34,34,34,0.94); color: white; padding: 8px 10px; border-radius: 6px; font-size: 12px; line-height: 1.35; opacity: 0; transform: translate(10px, -10px); white-space: nowrap; }}
    .note {{ color: var(--muted); font-size: 12px; line-height: 1.45; margin-top: 10px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <nav>
      <a href="index.html">Home</a>
      <a href="dashboard.html">First jobs</a>
      <a href="ncses_comparison.html">NCSES comparison</a>
      <a href="bachelors_countries.html">Bachelor countries</a>
      <a href="first_job_countries_non_us_bachelors.html">International Migration of Non-US PhDs</a>
    </nav>
    <h1>{html.escape(title)}</h1>
    <p class="sub">{html.escape(subtitle)}</p>
    {body}
  </div>
  {data_script}
</body>
</html>
"""


def write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
