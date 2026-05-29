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
NON_BACHELOR_RE = re.compile(
    r"\b(master|mba|m\.?\s*s\.?|m\.?\s*a\.?|ph\.?\s*d\.?|doctor|jd|j\.?\s*d\.?|"
    r"md|m\.?\s*d\.?|high school|certificate|associate)\b",
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
    degree = clean(row.get("degree")).lower()
    raw = clean(row.get("degree_raw"))
    if degree == "bachelor":
        return True
    if BACHELOR_RE.search(raw):
        return True
    return False


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
) -> tuple[Dict[str, str] | None, str]:
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
        country, _ = country_from_degree_row(row)
        after_phd = 1 if grad_year and end_year and end_year > grad_year else 0
        missing_end = 1 if end_year is None else 0
        explicit = 0 if degree == "bachelor" else 1
        contaminated = 1 if NON_BACHELOR_RE.search(raw) and degree != "bachelor" else 0
        year = end_year if end_year is not None else 9999
        missing_country = 1 if not country else 0
        return (after_phd, contaminated, explicit, missing_end, year, missing_country, degree_university(row).lower())

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
    label {{ color: var(--muted); font-size: 13px; }}
    select, input {{ font: 15px Georgia, "Times New Roman", serif; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; background: white; color: var(--ink); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-top: 1px solid var(--border); padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; }}
    .chart {{ width: 100%; height: 460px; display: block; }}
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
