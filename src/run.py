from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
import requests

# =========================
# Paths + Run Identity
# =========================
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

# Use one "now" for the entire run (keeps names consistent)
NOW = datetime.now()
RUN_TIMESTAMP = NOW.strftime("%Y-%m-%d_%H%M%S")  # clean timestamp format
RUN_MONTH = NOW.strftime("%Y-%m")
RUN_OUTPUT_DIR = OUTPUTS_DIR / RUN_MONTH


# =========================
# Schema (matches your dataset)
# =========================
REQUIRED_COLUMNS = [
    "service_date",
    "dob",
    "last_name",
    "first_name",
    "phone",
    "address",
    "state",
    "gender",
    "insurance_provider",
    "patient_id",
    "member_id",
    "member_group",
]


@dataclass
class RuleResult:
    status: str  # APPROVED / REVIEW / REJECTED
    reasons: List[str]


# =========================
# CLI Args
# =========================
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Healthcare Eligibility Automation")

    parser.add_argument(
        "--input",
        default=str(DATA_DIR / "patient_intake.csv"),
        help="Path to patient intake CSV (default: data/patient_intake.csv)",
    )
    parser.add_argument(
        "--rules",
        default=str(DATA_DIR / "insurance_rules.json"),
        help="Path to insurance rules JSON (default: data/insurance_rules.json)",
    )
    parser.add_argument(
        "--archive-input",
        action="store_true",
        help="If set, copies the input CSV into this run's output folder for audit continuity.",
    )

    # API mode
    parser.add_argument(
        "--api-url",
        default="",
        help="If set, calls this eligibility API per record (e.g., http://127.0.0.1:8000). "
             "If the API fails, falls back to local rules.",
    )
    parser.add_argument(
        "--api-timeout",
        type=float,
        default=5.0,
        help="Eligibility API timeout (seconds). Default 5.",
    )

    return parser.parse_args()


# =========================
# Logging + IO
# =========================
def setup_logging() -> None:
    RUN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RUN_OUTPUT_DIR / f"run_{RUN_TIMESTAMP}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )


def load_rules(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# =========================
# Parsers / Validators
# =========================
def parse_us_date(value: str) -> Tuple[date | None, str | None]:
    """Parse US-style dates like 12/31/2024 or 7/4/2025."""
    if value is None or str(value).strip() == "":
        return None, "MISSING_DATE"

    raw = str(value).strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).date(), None
        except ValueError:
            continue

    return None, "INVALID_DATE_FORMAT"


def normalize_phone(value: str) -> str:
    return re.sub(r"\D+", "", str(value or ""))


# --- Reason categorization (team routing) ---
INTAKE_REASON_PREFIXES = ("DOB_", "SERVICE_DATE_", "MISSING_")
INTAKE_REASONS_EXACT = {"PHONE_INVALID_LENGTH"}

INSURANCE_REASONS_EXACT = {
    "PAYER_NOT_SUPPORTED",
    "MISSING_MEMBER_ID",
    "MEMBER_ID_INVALID_FORMAT",
    "MISSING_MEMBER_GROUP",
    "MEMBER_GROUP_INVALID_FORMAT",
    "COVERAGE_POSSIBLY_INACTIVE",
    "API_FALLBACK_USED",  # treat API fallback as insurance-side visibility by default
}


def split_reason_domains(reasons_pipe: str) -> Tuple[List[str], List[str]]:
    """Return (intake_reasons, insurance_reasons)."""
    reasons = [r.strip() for r in str(reasons_pipe or "").split("|") if r.strip()]

    intake: List[str] = []
    insurance: List[str] = []

    for r in reasons:
        if r in INSURANCE_REASONS_EXACT:
            insurance.append(r)
        elif r in INTAKE_REASONS_EXACT or r.startswith(INTAKE_REASON_PREFIXES):
            intake.append(r)
        else:
            # Unknown reason codes default to intake review (safe)
            intake.append(r)

    return intake, insurance


def reasons_to_actions_intake(reasons: List[str]) -> Tuple[str, str]:
    """Return (next_action, priority) for intake team."""
    actions: List[str] = []
    priority = "MEDIUM"

    if any(r.startswith("DOB_") for r in reasons):
        actions.append("Correct DOB (MM/DD/YYYY) and re-run intake")
        priority = "HIGH"

    if any(r.startswith("SERVICE_DATE_") for r in reasons):
        actions.append("Correct service date (MM/DD/YYYY) and re-run intake")
        priority = "HIGH"

    if any(r.startswith("MISSING_") for r in reasons):
        actions.append("Complete missing required intake fields (demographics/ID/insurance/provider/state)")

    if "PHONE_INVALID_LENGTH" in reasons:
        actions.append("Verify phone number (10 digits)")

    if not actions:
        actions.append("Review intake record manually")

    seen = set()
    actions = [a for a in actions if not (a in seen or seen.add(a))]
    return " ; ".join(actions), priority


def reasons_to_actions_insurance(reasons: List[str]) -> Tuple[str, str]:
    """Return (next_action, priority) for insurance team."""
    actions: List[str] = []
    priority = "MEDIUM"

    if "API_FALLBACK_USED" in reasons:
        actions.append("API unavailable—processed using local rules (verify eligibility manually if needed)")

    if "PAYER_NOT_SUPPORTED" in reasons:
        actions.append("Payer not supported—collect alternate insurance or set SelfPay")
        priority = "HIGH"

    if "MISSING_MEMBER_ID" in reasons:
        actions.append("Collect member ID from insurance card")
        priority = "HIGH"

    if "MEMBER_ID_INVALID_FORMAT" in reasons:
        actions.append("Verify member ID format (ID-##########)")
        priority = "HIGH"

    if "MISSING_MEMBER_GROUP" in reasons:
        actions.append("Collect member group number (G-###### to G-#########)")

    if "MEMBER_GROUP_INVALID_FORMAT" in reasons:
        actions.append("Verify member group number format (G-###### to G-#########)")

    if "COVERAGE_POSSIBLY_INACTIVE" in reasons:
        actions.append("Verify active coverage in payer portal / call payer")
        priority = "HIGH"

    if not actions:
        actions.append("Review insurance details manually")

    seen = set()
    actions = [a for a in actions if not (a in seen or seen.add(a))]
    return " ; ".join(actions), priority


# =========================
# Local Eligibility Logic
# =========================
def validate_row(row: pd.Series, rules: Dict[str, Any]) -> RuleResult:
    reasons: List[str] = []

    for col in ["patient_id", "first_name", "last_name", "insurance_provider", "state"]:
        if str(row.get(col, "")).strip() == "":
            reasons.append(f"MISSING_{col.upper()}")

    dob, dob_err = parse_us_date(row.get("dob"))
    if dob_err:
        reasons.append(f"DOB_{dob_err}")

    svc_date, svc_err = parse_us_date(row.get("service_date"))
    if svc_err:
        reasons.append(f"SERVICE_DATE_{svc_err}")

    phone = normalize_phone(row.get("phone"))
    if phone and len(phone) != 10:
        reasons.append("PHONE_INVALID_LENGTH")

    provider = str(row.get("insurance_provider", "")).strip()
    member_id = str(row.get("member_id", "")).strip()
    member_group = str(row.get("member_group", "")).strip()

    if provider and provider not in rules:
        reasons.append("PAYER_NOT_SUPPORTED")

    if provider in rules:
        payer = rules[provider]

        member_id_regex = payer.get("member_id_regex", r"^ID-\d{10}$")
        group_regex = payer.get("group_regex", r"^G-\d{6,9}$")
        requires_group = bool(payer.get("requires_group_number", False))

        if provider != "SelfPay":
            if member_id == "":
                reasons.append("MISSING_MEMBER_ID")
            elif not re.match(member_id_regex, member_id):
                reasons.append("MEMBER_ID_INVALID_FORMAT")

        if requires_group and member_group == "":
            reasons.append("MISSING_MEMBER_GROUP")
        elif member_group and not re.match(group_regex, member_group):
            reasons.append("MEMBER_GROUP_INVALID_FORMAT")

        if svc_date and provider != "SelfPay":
            active_days = int(payer.get("active_coverage_days", 365))
            cutoff = date.today() - timedelta(days=active_days)
            if svc_date < cutoff:
                reasons.append("COVERAGE_POSSIBLY_INACTIVE")

    hard_reject_prefixes = ("MISSING_", "DOB_", "SERVICE_DATE_")
    if any(r.startswith(hard_reject_prefixes) for r in reasons):
        status = "REJECTED"
    elif "PAYER_NOT_SUPPORTED" in reasons or "COVERAGE_POSSIBLY_INACTIVE" in reasons:
        status = "REVIEW"
    elif reasons:
        status = "REVIEW"
    else:
        status = "APPROVED"

    return RuleResult(status=status, reasons=reasons)


# =========================
# API Mode + Fallback
# =========================
def call_eligibility_api(api_url: str, payload: dict, timeout: float) -> dict:
    url = api_url.rstrip("/") + "/eligibility"
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def validate_row_with_api_fallback(
    row: pd.Series,
    rules: Dict[str, Any],
    api_url: str,
    api_timeout: float,
) -> Tuple[RuleResult, bool, str]:
    """
    Returns: (RuleResult, api_used, api_error)

    - If api_url provided, attempt API call.
    - If API fails, log warning and fall back to local validate_row.
    """
    api_url = (api_url or "").strip()
    if not api_url:
        return validate_row(row, rules), False, ""

    payload = {
        "insurance_provider": str(row.get("insurance_provider", "")).strip(),
        "member_id": str(row.get("member_id", "")).strip(),
        "member_group": str(row.get("member_group", "")).strip(),
        "dob": str(row.get("dob", "")).strip(),
        "service_date": str(row.get("service_date", "")).strip(),
    }

    try:
        api_result = call_eligibility_api(api_url, payload, api_timeout)

        status = str(api_result.get("status", "REVIEW")).strip().upper()
        reasons = api_result.get("reasons", [])
        if not isinstance(reasons, list):
            reasons = []

        reasons = [str(r).strip() for r in reasons if str(r).strip()]
        return RuleResult(status=status, reasons=reasons), True, ""

    except Exception as e:
        logging.warning(
            f"Eligibility API failed for patient_id={row.get('patient_id','')}: {e} | Falling back to local rules."
        )
        local_result = validate_row(row, rules)
        local_result.reasons.append("API_FALLBACK_USED")
        return local_result, False, str(e)


# =========================
# Reporting
# =========================
def generate_summary(results_df: pd.DataFrame) -> Dict[str, Any]:
    total = len(results_df)
    status_counts = results_df["status"].value_counts(dropna=False).to_dict()

    reason_series = (
        results_df["reasons"]
        .fillna("")
        .astype(str)
        .str.split("|")
        .explode()
        .str.strip()
    )
    reason_series = reason_series[reason_series != ""]
    top_reasons = reason_series.value_counts().head(10).to_dict()

    api_used_counts = {}
    if "api_used" in results_df.columns:
        api_used_counts = results_df["api_used"].value_counts(dropna=False).to_dict()

    return {
        "total_records": total,
        "status_counts": status_counts,
        "api_used_counts": api_used_counts,
        "percent_approved": round((status_counts.get("APPROVED", 0) / total * 100) if total else 0, 2),
        "percent_review": round((status_counts.get("REVIEW", 0) / total * 100) if total else 0, 2),
        "percent_rejected": round((status_counts.get("REJECTED", 0) / total * 100) if total else 0, 2),
        "top_reasons": top_reasons,
        "generated_at": RUN_TIMESTAMP,
        "output_folder": str(RUN_OUTPUT_DIR),
    }


def build_work_queue(df_out: pd.DataFrame, domain: str) -> pd.DataFrame:
    """
    domain: 'intake' or 'insurance'
    Returns filtered work queue with next_action, priority, owner_queue.
    """
    queue = df_out[df_out["status"].isin(["REVIEW", "REJECTED"])].copy()
    if queue.empty:
        return queue

    split = queue["reasons"].fillna("").astype(str).apply(split_reason_domains)
    queue["intake_reasons"] = split.apply(lambda x: "|".join(x[0]))
    queue["insurance_reasons"] = split.apply(lambda x: "|".join(x[1]))

    if domain == "intake":
        queue = queue[queue["intake_reasons"].astype(str).str.len() > 0].copy()
        queue["owner_queue"] = "REGISTRATION"

        actions = queue["intake_reasons"].fillna("").astype(str).apply(
            lambda s: reasons_to_actions_intake([r for r in s.split("|") if r.strip()])
        )
        queue["next_action"] = actions.apply(lambda t: t[0])
        queue["priority"] = actions.apply(lambda t: t[1])
        queue["domain_reasons"] = queue["intake_reasons"]

    elif domain == "insurance":
        queue = queue[queue["insurance_reasons"].astype(str).str.len() > 0].copy()
        queue["owner_queue"] = "INSURANCE"

        actions = queue["insurance_reasons"].fillna("").astype(str).apply(
            lambda s: reasons_to_actions_insurance([r for r in s.split("|") if r.strip()])
        )
        queue["next_action"] = actions.apply(lambda t: t[0])
        queue["priority"] = actions.apply(lambda t: t[1])
        queue["domain_reasons"] = queue["insurance_reasons"]

    else:
        raise ValueError("domain must be 'intake' or 'insurance'")

    sort_priority = {"HIGH": 0, "MEDIUM": 1}
    queue["priority_sort"] = queue["priority"].map(sort_priority).fillna(9).astype(int)
    queue = queue.sort_values(["priority_sort", "last_name", "first_name"]).drop(columns=["priority_sort"])

    preferred_cols = [
        "status",
        "priority",
        "owner_queue",
        "next_action",
        "patient_id",
        "last_name",
        "first_name",
        "dob",
        "service_date",
        "insurance_provider",
        "member_id",
        "member_group",
        "phone",
        "address",
        "state",
        "gender",
        "api_used",
        "domain_reasons",
        "reasons",
        "api_error",
    ]
    cols = [c for c in preferred_cols if c in queue.columns] + [c for c in queue.columns if c not in preferred_cols]
    return queue[cols]


# =========================
# Main
# =========================
def main() -> None:
    args = parse_args()
    setup_logging()

    logging.info("Starting eligibility automation run...")
    logging.info(f"RUN_TIMESTAMP={RUN_TIMESTAMP} | RUN_OUTPUT_DIR={RUN_OUTPUT_DIR}")

    intake_path = Path(args.input)
    rules_path = Path(args.rules)

    if not intake_path.exists():
        raise FileNotFoundError(f"Missing input file: {intake_path}")
    if not rules_path.exists():
        raise FileNotFoundError(f"Missing rules file: {rules_path}")

    rules = load_rules(rules_path)
    df = pd.read_csv(intake_path, dtype=str).fillna("")

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Input is missing required columns: {missing_cols}")

    if args.archive_input:
        RUN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        archived = RUN_OUTPUT_DIR / f"input_{RUN_TIMESTAMP}.csv"
        shutil.copy2(intake_path, archived)
        logging.info(f"Archived input file to: {archived}")

    api_url = str(args.api_url).strip()
    api_timeout = float(args.api_timeout)
    logging.info(f"API mode: {'ON' if api_url else 'OFF'} | api_url={api_url or '(none)'} | timeout={api_timeout}s")

    statuses: List[str] = []
    reasons_list: List[str] = []
    api_used_list: List[str] = []
    api_error_list: List[str] = []

    for _, row in df.iterrows():
        result, api_used, api_err = validate_row_with_api_fallback(
            row=row,
            rules=rules,
            api_url=api_url,
            api_timeout=api_timeout,
        )

        statuses.append(result.status)
        reasons_list.append("|".join(result.reasons))
        api_used_list.append("YES" if api_used else "NO")
        api_error_list.append(api_err)

    df_out = df.copy()
    df_out["status"] = statuses
    df_out["reasons"] = reasons_list

    # ---- API metadata columns (place these here) ----
    df_out["api_used"] = api_used_list
    df_out["api_error"] = api_error_list
    # -----------------------------------------------

    RUN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results_csv = RUN_OUTPUT_DIR / f"eligibility_results_{RUN_TIMESTAMP}.csv"
    df_out.to_csv(results_csv, index=False)

    summary = generate_summary(df_out[["status", "reasons", "api_used"]])
    summary_path = RUN_OUTPUT_DIR / f"eligibility_summary_{RUN_TIMESTAMP}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    intake_queue_df = build_work_queue(df_out, domain="intake")
    insurance_queue_df = build_work_queue(df_out, domain="insurance")

    intake_queue_path = RUN_OUTPUT_DIR / f"intake_queue_{RUN_TIMESTAMP}.csv"
    insurance_queue_path = RUN_OUTPUT_DIR / f"insurance_queue_{RUN_TIMESTAMP}.csv"

    intake_queue_df.to_csv(intake_queue_path, index=False)
    insurance_queue_df.to_csv(insurance_queue_path, index=False)

    logging.info("Run complete.")
    logging.info(f"Wrote results: {results_csv}")
    logging.info(f"Wrote summary: {summary_path}")
    logging.info(f"Wrote intake queue: {intake_queue_path}")
    logging.info(f"Wrote insurance queue: {insurance_queue_path}")
    logging.info(f"Outputs stored in: {RUN_OUTPUT_DIR}")


if __name__ == "__main__":
    main()
