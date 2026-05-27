#!/usr/bin/env python3
"""Build a first-job dashboard input from the mapped post-PhD job history."""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
CODEX_DATA = ROOT / "codex_data"
OUTPUT_DIR = ROOT / "outputs" / "first_job_graphs"
OVERRIDES_JSON = ROOT / "config" / "first_job_overrides.json"

MAPPED_CSV = CODEX_DATA / "post_phd_job_history_mapped.csv"
NSF_CSV = CODEX_DATA / "goid_user_id_nsf.csv"
OUT_CSV = CODEX_DATA / "post_phd_first_job_dashboard_input.csv"
AUDIT_JSON = OUTPUT_DIR / "post_phd_first_job_dashboard_input_audit.json"
AUDIT_MD = OUTPUT_DIR / "post_phd_first_job_dashboard_input_audit.md"

NSF_FIELDS = ("nsf_primary", "nsf_major", "nsf_broad")

OUTPUT_FIELDS = [
    "pq_row_id",
    "goid",
    "author",
    "rev_user_id",
    "grad_year",
    "first_job_startdate",
    "first_job_enddate",
    "start_dt",
    "end_dt",
    "company_cleaned",
    "company_raw",
    "country",
    "rcid",
    "title_raw",
    "title_translated",
    "mapped_role_v3",
    "onet_title",
    "company_name",
    "ultimate_parent_rcid",
    "ultimate_parent_rcid_name",
    "ticker",
    "exchange_name",
    "cusip",
    "proquest_year",
    "nsf_primary",
    "nsf_major",
    "nsf_broad",
    "nsf_patch_source",
    "nsf_patch_key",
    "first_job_year",
    "first_job_company_norm",
    "revelio_company",
    "revelio_primary_name",
    "revelio_ultimate_parent_rcid",
    "revelio_ultimate_parent_name",
    "revelio_ticker",
    "revelio_exchange_name",
    "revelio_cusip",
    "revelio_isin",
    "revelio_cik",
    "revelio_gvkey",
    "revelio_naics_code",
    "revelio_year_founded",
    "compustat_gvkey",
    "compustat_cusip",
    "compustat_cik",
    "compustat_ticker",
    "compustat_company_name",
    "compustat_firm_status",
    "compustat_is_active",
    "compustat_sic",
    "compustat_naics",
    "compustat_ipodate",
    "compustat_ipo_year",
    "pitchbook_companyid",
    "pitchbook_companyname",
    "pitchbook_employees",
    "pitchbook_businessstatus",
    "pitchbook_exchange",
    "pitchbook_ticker",
    "pitchbook_yearfounded",
    "pitchbook_totalraised",
    "pitchbook_primaryindustrysector",
    "pitchbook_hqcountry",
    "first_vc_year",
    "dealclasses",
    "financingstatuses",
    "n_deals_total",
    "n_vc_rounds",
    "is_public_current_pitchbook",
    "classification_text",
    "base_company_source",
    "compustat_join_source",
    "pitchbook_join_source",
    "first_job_org_type",
    "classification_source",
    "first_job_org_type_final",
    "first_job_org_subtype_final",
    "classification_source_final",
    "classification_confidence_final",
    "job_order",
    "position_id",
    "position_number",
    "org_class",
    "org_match_status",
    "org_match_notes",
    "discern_matched",
    "discern_permno_adj",
    "discern_match_method",
    "public_listed_non_discern_matched",
    "non_us_corporation_matched",
    "pitchbook_startup_matched",
    "pitchbook_backed_in_job_year",
    "needs_manual_review",
    "source_job_org_type",
    "cchie_2021_value",
    "cchie_2021_catlabel",
    "cchie_2021_group",
    "cchie_2021_grplabel",
    "cchie_instnm_2021",
    "cchie_match_method",
    "public_listed_non_discern_evidence",
    "non_us_corporation_evidence",
    "pitchbook_startup_is_public",
]

HOSPITAL_RE = re.compile(
    r"\b("
    r"hospital|medical center|health system|healthcare|health care|clinic|"
    r"children'?s hospital|cancer center|health sciences center|medical school|"
    r"school of medicine|medicine|patient care|surgery|clinical"
    r")\b",
    re.IGNORECASE,
)
GOV_LAB_RE = re.compile(
    r"\b("
    r"national laborator(?:y|ies)|air force research laboratory|naval research laboratory|"
    r"naval surface warfare center|naval medical research|army research laboratory|"
    r"oak ridge|los alamos|sandia|lawrence livermore|"
    r"lawrence berkeley|brookhaven|fermi(?:lab)?|argonne|pacific northwest national laboratory|"
    r"jet propulsion laboratory|slac|ames laboratory|princeton plasma physics laboratory"
    r")\b",
    re.IGNORECASE,
)
GOV_PUBLIC_RE = re.compile(
    r"\b("
    r"department of|dept of|ministry of|agency|bureau of|office of|"
    r"national institutes? of health|nih|cdc|fda|nasa|noaa|nsf|usda|"
    r"environmental protection agency|epa|department of energy|department of defense|"
    r"air force|u\.?s\.? navy|u\.?s\.? army|government|public health|"
    r"federal reserve|world bank|international monetary fund|state of [a-z ]+"
    r")\b",
    re.IGNORECASE,
)
UNIVERSITY_RE = re.compile(
    r"\b("
    r"university|college|school of|institute of technology|polytechnic|"
    r"academy|seminary|faculty of|department of .* university"
    r")\b",
    re.IGNORECASE,
)
RESEARCH_NONPROFIT_RE = re.compile(
    r"\b("
    r"research institute|institute for|institute of|foundation|observatory|museum|"
    r"research center|research centre|laboratory|labs?|society|association|"
    r"council|consortium"
    r")\b",
    re.IGNORECASE,
)
SELF_EMPLOYED_RE = re.compile(
    r"\b(self[- ]employed|freelance|independent consultant|consultant|sole proprietor)\b",
    re.IGNORECASE,
)
BUSINESS_RE = re.compile(
    r"\b("
    r"inc|llc|corp|corporation|company|co\.?|ltd|limited|plc|gmbh|sarl|"
    r"lp|llp|partners|capital|consulting|technologies|systems|solutions"
    r")\b|\.com",
    re.IGNORECASE,
)
HOSPITAL_NAICS_RE = re.compile(
    r"\b(hospital|medical|surgical|health|clinic|outpatient|ambulatory|physician)\b",
    re.IGNORECASE,
)
GOV_NAICS_RE = re.compile(
    r"\b(administration of|government|public order|space research and technology|national security)\b",
    re.IGNORECASE,
)
UNIVERSITY_NAICS_RE = re.compile(
    r"\b(colleges|universities|professional schools|junior colleges)\b",
    re.IGNORECASE,
)
RESEARCH_NAICS_RE = re.compile(
    r"\b(research and development|scientific research|social advocacy|grantmaking)\b",
    re.IGNORECASE,
)


def norm_id(value: str | None) -> str:
    text = (value or "").strip()
    if text.endswith(".0"):
        return text[:-2]
    return text


def safe_float(value: str | None) -> float:
    text = (value or "").strip()
    if not text:
        return math.inf
    try:
        return float(text)
    except ValueError:
        return math.inf


def tie_key(row: Dict[str, str]) -> Tuple[float, float, float]:
    return (
        safe_float(row.get("job_start_year")),
        safe_float(row.get("position_number")),
        safe_float(row.get("position_id")),
    )


def single_nonempty_maps(
    rows: Iterable[Dict[str, str]],
    key_field: str,
) -> Tuple[Dict[str, Tuple[str, str, str]], set[str], int]:
    values: Dict[str, set[Tuple[str, str, str]]] = defaultdict(set)
    for row in rows:
        key = norm_id(row.get(key_field))
        if not key:
            continue
        values[key].add(tuple((row.get(field) or "").strip() for field in NSF_FIELDS))

    out: Dict[str, Tuple[str, str, str]] = {}
    ambiguous: set[str] = set()
    empty_only = 0
    for key, tuples in values.items():
        nonempty = {item for item in tuples if item[2]}
        if len(nonempty) == 1:
            out[key] = next(iter(nonempty))
        elif len(nonempty) > 1:
            ambiguous.add(key)
        else:
            empty_only += 1
    return out, ambiguous, empty_only


def load_nsf_crosswalk() -> Dict[str, object]:
    with NSF_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    goid_map, goid_ambiguous, goid_empty_only = single_nonempty_maps(rows, "goid")
    user_map, user_ambiguous, user_empty_only = single_nonempty_maps(rows, "rev_user_id")
    return {
        "goid_map": goid_map,
        "user_map": user_map,
        "row_count": len(rows),
        "goid_keys": len({norm_id(row.get("goid")) for row in rows if norm_id(row.get("goid"))}),
        "user_keys": len(
            {norm_id(row.get("rev_user_id")) for row in rows if norm_id(row.get("rev_user_id"))}
        ),
        "safe_goid_keys": len(goid_map),
        "safe_user_keys": len(user_map),
        "ambiguous_goid_keys": len(goid_ambiguous),
        "ambiguous_user_keys": len(user_ambiguous),
        "empty_only_goid_keys": goid_empty_only,
        "empty_only_user_keys": user_empty_only,
    }


def load_overrides() -> Dict[str, object]:
    if not OVERRIDES_JSON.exists():
        return {
            "classification_exact_overrides": {},
            "classification_regex_overrides": [],
        }
    with OVERRIDES_JSON.open(encoding="utf-8") as f:
        data = json.load(f)
    return {
        "classification_exact_overrides": data.get("classification_exact_overrides", {}),
        "classification_regex_overrides": data.get("classification_regex_overrides", []),
    }


OVERRIDES = load_overrides()


def evidence_text(row: Dict[str, str]) -> str:
    return " | ".join(
        (row.get(field) or "").strip()
        for field in [
            "company_raw",
            "company_cleaned",
            "company_name",
            "revelio_primary_name",
            "ultimate_parent_company_name",
            "revelio_ultimate_parent_name",
            "position_naics_description",
        ]
        if (row.get(field) or "").strip()
    )


def canonical_names(row: Dict[str, str]) -> list[str]:
    names = []
    for field in [
        "revelio_primary_name",
        "company_name",
        "company_raw",
        "company_cleaned",
        "ultimate_parent_company_name",
        "revelio_ultimate_parent_name",
    ]:
        name = re.sub(r"\s+", " ", (row.get(field) or "").strip(" |,;"))
        if name and name not in names:
            names.append(name)
    return names


def override_classification(row: Dict[str, str]) -> Tuple[str, str, str, str] | None:
    exact = OVERRIDES.get("classification_exact_overrides", {})
    if isinstance(exact, dict):
        for name in canonical_names(row):
            override = exact.get(name.lower())
            if isinstance(override, dict) and override.get("org_type"):
                return (
                    str(override["org_type"]),
                    "Manual exact override",
                    str(override.get("source", "override_exact")),
                    str(override.get("confidence", "high")),
                )

    regex_overrides = OVERRIDES.get("classification_regex_overrides", [])
    text = evidence_text(row).lower()
    if isinstance(regex_overrides, list):
        for override in regex_overrides:
            if not isinstance(override, dict):
                continue
            pattern = override.get("pattern", "")
            if pattern and re.search(str(pattern), text):
                return (
                    str(override["org_type"]),
                    "Manual regex override",
                    str(override.get("source", "override_regex")),
                    str(override.get("confidence", "high")),
                )
    return None


def has_listing_evidence(row: Dict[str, str]) -> bool:
    evidence = " | ".join(
        [
            row.get("public_listed_non_discern_evidence", ""),
            row.get("non_us_corporation_evidence", ""),
            row.get("classification_source", ""),
        ]
    ).lower()
    if any(token in evidence for token in ["ticker_present", "exchange_present", "listed", "public"]):
        return True
    return any(
        (row.get(field) or "").strip()
        for field in [
            "position_ticker",
            "position_exchange",
            "revelio_ticker",
            "compustat_ticker",
            "pitchbook_startup_ticker",
            "pitchbook_startup_exchange",
        ]
    )


def mapped_final_classification(row: Dict[str, str]) -> Tuple[str, str, str, str]:
    org_class = (row.get("org_class") or "").strip()
    text = evidence_text(row)
    naics = row.get("position_naics_description", "")

    override = override_classification(row)
    if override is not None:
        return override

    if org_class == "cchie":
        value = (row.get("cchie_2021_value") or "").strip()
        label = (row.get("cchie_2021_catlabel") or "").strip()
        if value == "15":
            return (
                "University / Academic Institution",
                "R1 university",
                "mapped_cchie_carnegie_15_r1",
                "high",
            )
        if value == "16":
            return (
                "University / Academic Institution",
                "R2 university",
                "mapped_cchie_carnegie_16_r2",
                "high",
            )
        if value == "25":
            return (
                "Hospital / Health System",
                "Medical school / health sciences center",
                "mapped_cchie_carnegie_25_medical_school",
                "high",
            )
        if value == "27":
            if HOSPITAL_RE.search(text) or HOSPITAL_NAICS_RE.search(naics):
                return (
                    "Hospital / Health System",
                    "Special-focus research institution, medical/health",
                    "mapped_cchie_carnegie_27_medical_research_institution",
                    "high",
                )
            return (
                "Research Institute / Nonprofit",
                "Special-focus research institution",
                "mapped_cchie_carnegie_27_research_institution",
                "high",
            )
        if HOSPITAL_RE.search(text) and HOSPITAL_NAICS_RE.search(naics):
            return (
                "Hospital / Health System",
                label or "CCHIE health institution",
                "mapped_cchie_health_keyword_and_naics",
                "medium",
            )
        return (
            "University / Academic Institution",
            label or "CCHIE institution",
            "mapped_cchie_institution",
            "high",
        )

    if org_class == "discern":
        return (
            "Listed Company",
            "US public firm / DISCERN",
            "mapped_discern_public_firm",
            "high",
        )
    if org_class == "public_listed_non_discern":
        return (
            "Listed Company",
            "US public/listed non-DISCERN",
            "mapped_public_listed_non_discern",
            "high",
        )

    if org_class == "non_us_corporation":
        if has_listing_evidence(row):
            return (
                "Listed Company",
                "Non-US listed company",
                "mapped_non_us_listed_company",
                "medium",
            )
        return (
            "Business (Unclassified)",
            "Non-US corporation, listing unverified",
            "mapped_non_us_corporation_unverified_listing",
            "medium",
        )

    if org_class == "pitchbook":
        backed = (row.get("pitchbook_backed_in_job_year") or "").strip()
        if backed == "1":
            subtype = "VC-backed by job year"
            source = "mapped_pitchbook_startup_backed_by_job_year"
            confidence = "high"
        elif backed == "0":
            subtype = "PitchBook startup, backing after job year"
            source = "mapped_pitchbook_startup_backing_after_job_year"
            confidence = "medium"
        else:
            subtype = "PitchBook startup, backing timing unknown"
            source = "mapped_pitchbook_startup_backing_timing_unknown"
            confidence = "medium"
        return ("Startup / VC-backed Private Firm", subtype, source, confidence)

    source_type = (row.get("job_org_type") or "").strip()
    if source_type in {"Government Agency / Public Sector", "Government Lab", "Hospital / Health System"}:
        return (
            source_type,
            "Source classification fallback",
            "fallback_source_job_org_type_specific",
            "medium",
        )

    if SELF_EMPLOYED_RE.search(text):
        return (
            "Self-Employed / Independent",
            "Self-employed / freelance",
            "fallback_self_employed_keyword",
            "medium",
        )
    if HOSPITAL_RE.search(text) or HOSPITAL_NAICS_RE.search(naics):
        return (
            "Hospital / Health System",
            "Hospital / health keyword or NAICS",
            "fallback_hospital_keyword_or_naics",
            "medium",
        )
    if GOV_LAB_RE.search(text):
        return (
            "Government Lab",
            "Government lab keyword",
            "fallback_government_lab_keyword",
            "medium",
        )
    if GOV_PUBLIC_RE.search(text) or GOV_NAICS_RE.search(naics):
        return (
            "Government Agency / Public Sector",
            "Government/public keyword or NAICS",
            "fallback_government_public_keyword_or_naics",
            "medium",
        )
    if UNIVERSITY_RE.search(text) or UNIVERSITY_NAICS_RE.search(naics):
        return (
            "University / Academic Institution",
            "Academic keyword or NAICS",
            "fallback_university_keyword_or_naics",
            "medium",
        )
    if RESEARCH_NONPROFIT_RE.search(text) or RESEARCH_NAICS_RE.search(naics):
        return (
            "Research Institute / Nonprofit",
            "Research/nonprofit keyword or NAICS",
            "fallback_research_nonprofit_keyword_or_naics",
            "medium",
        )
    if BUSINESS_RE.search(text):
        return (
            "Business (Unclassified)",
            "Business-like residual",
            "fallback_business_keyword",
            "low",
        )
    return (
        "Other / Unclassified",
        "No accepted organization-class signal",
        "fallback_other_unclassified",
        "low",
    )


def classification_source_from_mapped(row: Dict[str, str]) -> str:
    org_class = (row.get("org_class") or "").strip() or "unmatched"
    status = (row.get("org_match_status") or "").strip()
    method = ""
    if org_class == "discern":
        method = (row.get("discern_match_method") or "").strip()
    elif org_class == "cchie":
        method = (row.get("cchie_match_method") or "").strip()
    elif org_class == "pitchbook":
        method = (row.get("pitchbook_startup_match_method") or "").strip()
    elif org_class == "public_listed_non_discern":
        method = (row.get("public_listed_non_discern_evidence") or "").strip()
    elif org_class == "non_us_corporation":
        method = (row.get("non_us_corporation_evidence") or "").strip()

    parts = ["post_phd_mapped", org_class]
    if status:
        parts.append(status)
    if method:
        parts.append(method)
    return "__".join(parts)


def patch_nsf(row: Dict[str, str], nsf: Dict[str, object]) -> Tuple[str, str]:
    if (row.get("nsf_broad") or "").strip():
        return "native", ""

    goid = norm_id(row.get("goid"))
    rev_user_id = norm_id(row.get("rev_user_id"))
    goid_map: Dict[str, Tuple[str, str, str]] = nsf["goid_map"]  # type: ignore[assignment]
    user_map: Dict[str, Tuple[str, str, str]] = nsf["user_map"]  # type: ignore[assignment]

    if goid and goid in goid_map:
        values = goid_map[goid]
        for field, value in zip(NSF_FIELDS, values):
            row[field] = value
        return "goid_user_id_nsf:goid", goid

    if rev_user_id and rev_user_id in user_map:
        values = user_map[rev_user_id]
        for field, value in zip(NSF_FIELDS, values):
            row[field] = value
        return "goid_user_id_nsf:rev_user_id", rev_user_id

    return "missing", ""


def adapted_row(row: Dict[str, str], nsf: Dict[str, object]) -> Dict[str, str]:
    final_type, final_subtype, final_source, final_confidence = mapped_final_classification(row)
    out = {field: "" for field in OUTPUT_FIELDS}
    out.update(
        {
            "pq_row_id": norm_id(row.get("goid")),
            "goid": norm_id(row.get("goid")),
            "author": "",
            "rev_user_id": norm_id(row.get("rev_user_id")),
            "grad_year": (row.get("proquest_year") or "").strip(),
            "first_job_startdate": row.get("start_dt", ""),
            "first_job_enddate": row.get("end_dt", ""),
            "start_dt": row.get("start_dt", ""),
            "end_dt": row.get("end_dt", ""),
            "company_cleaned": row.get("company_cleaned", ""),
            "company_raw": row.get("company_raw", ""),
            "country": row.get("country", ""),
            "rcid": row.get("rcid", ""),
            "company_name": row.get("company_name", ""),
            "ultimate_parent_rcid": row.get("ultimate_parent_rcid", ""),
            "ultimate_parent_rcid_name": row.get("ultimate_parent_company_name", ""),
            "ticker": row.get("position_ticker", ""),
            "exchange_name": row.get("position_exchange", ""),
            "cusip": row.get("position_cusip", ""),
            "proquest_year": row.get("proquest_year", ""),
            "nsf_primary": row.get("nsf_primary", ""),
            "nsf_major": row.get("nsf_major", ""),
            "nsf_broad": row.get("nsf_broad", ""),
            "first_job_year": row.get("job_start_year", ""),
            "first_job_company_norm": row.get("job_company_norm", ""),
            "revelio_company": row.get("revelio_primary_name", ""),
            "revelio_primary_name": row.get("revelio_primary_name", ""),
            "revelio_ultimate_parent_rcid": row.get("ultimate_parent_rcid", ""),
            "revelio_ultimate_parent_name": row.get("revelio_ultimate_parent_name", ""),
            "revelio_ticker": row.get("revelio_ticker", ""),
            "revelio_cusip": row.get("revelio_cusip", ""),
            "revelio_cik": row.get("revelio_cik", ""),
            "revelio_gvkey": row.get("revelio_gvkey", ""),
            "compustat_gvkey": row.get("compustat_gvkey", ""),
            "compustat_cusip": row.get("compustat_cusip", ""),
            "compustat_cik": row.get("compustat_cik", ""),
            "compustat_ticker": row.get("compustat_ticker", ""),
            "compustat_company_name": row.get("compustat_company_name", ""),
            "pitchbook_companyid": row.get("pitchbook_startup_companyid")
            or row.get("pitchbook_companyid", ""),
            "pitchbook_companyname": row.get("pitchbook_startup_company_name", ""),
            "pitchbook_businessstatus": row.get("pitchbook_startup_business_status", ""),
            "pitchbook_exchange": row.get("pitchbook_startup_exchange", ""),
            "pitchbook_ticker": row.get("pitchbook_startup_ticker", ""),
            "pitchbook_yearfounded": row.get("pitchbook_startup_year_founded", ""),
            "pitchbook_hqcountry": row.get("pitchbook_startup_hqcountry", ""),
            "first_vc_year": row.get("first_vc_year", ""),
            "classification_text": row.get("org_match_notes", ""),
            "base_company_source": "post_phd_job_history_mapped",
            "compustat_join_source": row.get("discern_match_method", "")
            or row.get("public_listed_non_discern_evidence", ""),
            "pitchbook_join_source": row.get("pitchbook_startup_match_method", ""),
            "first_job_org_type": final_type,
            "classification_source": final_source,
            "first_job_org_type_final": final_type,
            "first_job_org_subtype_final": final_subtype,
            "classification_source_final": final_source,
            "classification_confidence_final": final_confidence,
            "job_order": row.get("job_order", ""),
            "position_id": row.get("position_id", ""),
            "position_number": row.get("position_number", ""),
            "org_class": row.get("org_class", ""),
            "org_match_status": row.get("org_match_status", ""),
            "org_match_notes": row.get("org_match_notes", ""),
            "discern_matched": row.get("discern_matched", ""),
            "discern_permno_adj": row.get("discern_permno_adj", ""),
            "discern_match_method": row.get("discern_match_method", ""),
            "public_listed_non_discern_matched": row.get("public_listed_non_discern_matched", ""),
            "non_us_corporation_matched": row.get("non_us_corporation_matched", ""),
            "pitchbook_startup_matched": row.get("pitchbook_startup_matched", ""),
            "pitchbook_backed_in_job_year": row.get("pitchbook_backed_in_job_year", ""),
            "needs_manual_review": row.get("needs_manual_review", ""),
            "source_job_org_type": row.get("job_org_type", ""),
            "cchie_2021_value": row.get("cchie_2021_value", ""),
            "cchie_2021_catlabel": row.get("cchie_2021_catlabel", ""),
            "cchie_2021_group": row.get("cchie_2021_group", ""),
            "cchie_2021_grplabel": row.get("cchie_2021_grplabel", ""),
            "cchie_instnm_2021": row.get("cchie_instnm_2021", ""),
            "cchie_match_method": row.get("cchie_match_method", ""),
            "public_listed_non_discern_evidence": row.get("public_listed_non_discern_evidence", ""),
            "non_us_corporation_evidence": row.get("non_us_corporation_evidence", ""),
            "pitchbook_startup_is_public": row.get("pitchbook_startup_is_public", ""),
        }
    )
    source, key = patch_nsf(out, nsf)
    out["nsf_patch_source"] = source
    out["nsf_patch_key"] = key
    return out


def read_first_job_rows(nsf: Dict[str, object]) -> Tuple[list[Dict[str, str]], Dict[str, object]]:
    chosen: Dict[str, Dict[str, str]] = {}
    diagnostics = Counter()
    tied_user_ids: set[str] = set()

    with MAPPED_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            diagnostics["mapped_rows"] += 1
            rev_user_id = norm_id(row.get("rev_user_id"))
            if not rev_user_id:
                diagnostics["rows_missing_rev_user_id"] += 1
                continue
            if (row.get("job_order") or "").strip() != "1":
                continue
            diagnostics["job_order_1_rows"] += 1
            current = chosen.get(rev_user_id)
            if current is None:
                chosen[rev_user_id] = row
                continue
            diagnostics["job_order_1_tie_rows"] += 1
            tied_user_ids.add(rev_user_id)
            if tie_key(row) < tie_key(current):
                chosen[rev_user_id] = row

    rows = [adapted_row(row, nsf) for row in chosen.values()]
    diagnostics["first_job_users"] = len(rows)
    diagnostics["users_with_tied_job_order_1"] = len(tied_user_ids)
    diagnostics["extra_tied_job_order_1_rows"] = diagnostics["job_order_1_rows"] - len(rows)
    diagnostics["missing_nsf_after_patch"] = sum(1 for row in rows if not row["nsf_broad"].strip())
    diagnostics["native_nsf"] = sum(1 for row in rows if row["nsf_patch_source"] == "native")
    diagnostics["patched_nsf_by_goid"] = sum(
        1 for row in rows if row["nsf_patch_source"] == "goid_user_id_nsf:goid"
    )
    diagnostics["patched_nsf_by_rev_user_id"] = sum(
        1 for row in rows if row["nsf_patch_source"] == "goid_user_id_nsf:rev_user_id"
    )
    diagnostics["org_class_counts"] = dict(Counter(row["org_class"] for row in rows))
    diagnostics["first_job_org_type_counts"] = dict(Counter(row["first_job_org_type"] for row in rows))
    diagnostics["first_job_org_subtype_counts"] = dict(
        Counter(row["first_job_org_subtype_final"] for row in rows)
    )
    diagnostics["classification_source_final_counts"] = dict(
        Counter(row["classification_source_final"] for row in rows)
    )
    diagnostics["nsf_patch_source_counts"] = dict(Counter(row["nsf_patch_source"] for row in rows))
    return rows, dict(diagnostics)


def write_rows(rows: Sequence[Dict[str, str]]) -> None:
    CODEX_DATA.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_audit(nsf: Dict[str, object], diagnostics: Dict[str, object]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    audit = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mapped_input": str(MAPPED_CSV),
        "nsf_crosswalk": str(NSF_CSV),
        "output_csv": str(OUT_CSV),
        "job_selection_rule": "job_order == 1; ties by earliest job_start_year, lowest position_number, lowest position_id",
        "nsf_patch_rule": "native NSF fields, else safe goid match, else safe rev_user_id match, else missing",
        "nsf_crosswalk_diagnostics": {
            key: value for key, value in nsf.items() if not key.endswith("_map")
        },
        "dashboard_input_diagnostics": diagnostics,
    }
    AUDIT_JSON.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")

    source_counts = diagnostics.get("nsf_patch_source_counts", {})
    if not isinstance(source_counts, dict):
        source_counts = {}
    org_counts = diagnostics.get("first_job_org_type_counts", {})
    if not isinstance(org_counts, dict):
        org_counts = {}
    lines = [
        "# Post-PhD First-Job Dashboard Input Audit",
        "",
        f"- Created (UTC): `{audit['created_at_utc']}`",
        f"- Mapped input: `{MAPPED_CSV}`",
        f"- NSF crosswalk: `{NSF_CSV}`",
        f"- Output CSV: `{OUT_CSV}`",
        f"- Job selection: {audit['job_selection_rule']}",
        f"- NSF patching: {audit['nsf_patch_rule']}",
        "",
        "## Counts",
        "",
        f"- Mapped rows scanned: `{diagnostics.get('mapped_rows', 0)}`",
        f"- `job_order == 1` rows: `{diagnostics.get('job_order_1_rows', 0)}`",
        f"- First-job users written: `{diagnostics.get('first_job_users', 0)}`",
        f"- Users with tied `job_order == 1` rows: `{diagnostics.get('users_with_tied_job_order_1', 0)}`",
        f"- Extra tied `job_order == 1` rows resolved: `{diagnostics.get('extra_tied_job_order_1_rows', 0)}`",
        f"- Missing NSF after patch: `{diagnostics.get('missing_nsf_after_patch', 0)}`",
        "",
        "## NSF Sources",
        "",
    ]
    for source, count in sorted(source_counts.items()):
        lines.append(f"- `{source}`: `{count}`")
    lines.extend(["", "## Final Organization Classes", ""])
    for org_type, count in sorted(org_counts.items()):
        lines.append(f"- `{org_type}`: `{count}`")
    lines.append("")
    AUDIT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    nsf = load_nsf_crosswalk()
    rows, diagnostics = read_first_job_rows(nsf)
    write_rows(rows)
    write_audit(nsf, diagnostics)
    print(f"Wrote {len(rows):,} rows to {OUT_CSV}")
    print(f"Missing NSF after patch: {diagnostics['missing_nsf_after_patch']:,}")
    print(f"Audit: {AUDIT_MD}")


if __name__ == "__main__":
    main()
