import io
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st


# =========================
# Project Paths
# =========================
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
SRC_DIR = PROJECT_ROOT / "src"


# =========================
# Required Intake Schema
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


# =========================
# Streamlit Page Config
# =========================
st.set_page_config(
    page_title="Healthcare Eligibility Automation",
    layout="wide",
)

st.title("Healthcare Intake & Insurance Eligibility Automation")
st.caption(
    "Upload a patient intake CSV → validate → route intake vs insurance issues → download results."
)


# =========================
# Sidebar Configuration
# =========================
st.sidebar.header("Configuration")

rules_path = st.sidebar.text_input(
    "Insurance Rules JSON",
    value=str(DATA_DIR / "insurance_rules.json"),
)

archive_input = st.sidebar.toggle(
    "Archive uploaded input into output folder",
    value=True,
)

st.sidebar.divider()
st.sidebar.caption("Tip: Column headers must match the required schema exactly.")


# =========================
# Validation State Defaults
# (Must exist before button)
# =========================
csv_is_valid = False
df_preview = None
missing_cols: list[str] = []
extra_cols: list[str] = []


# =========================
# Helper Functions
# =========================
def validate_columns(df: pd.DataFrame, required_cols: list[str]) -> tuple[list[str], list[str]]:
    cols = [c.strip() for c in df.columns.tolist()]
    missing = [c for c in required_cols if c not in cols]
    extra = [c for c in cols if c not in required_cols]
    return missing, extra


def run_pipeline(input_csv: Path, rules_json: Path, archive: bool) -> str:
    """Run run.py as a subprocess so we reuse all batch logic."""
    cmd = [
        sys.executable,
        str(SRC_DIR / "run.py"),
        "--input",
        str(input_csv),
        "--rules",
        str(rules_json),
    ]
    if archive:
        cmd.append("--archive-input")

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")


def find_latest_month(outputs_root: Path) -> Path | None:
    if not outputs_root.exists():
        return None
    months = sorted([p for p in outputs_root.iterdir() if p.is_dir()], reverse=True)
    return months[0] if months else None


def find_latest_run_files(month_dir: Path) -> dict:
    results = sorted(month_dir.glob("eligibility_results_*.csv"), reverse=True)
    if not results:
        return {}

    latest = results[0]
    token = latest.stem.replace("eligibility_results_", "")

    return {
        "results": latest,
        "summary": month_dir / f"eligibility_summary_{token}.json",
        "intake": month_dir / f"intake_queue_{token}.csv",
        "insurance": month_dir / f"insurance_queue_{token}.csv",
        "log": month_dir / f"run_{token}.log",
        "token": token,
        "folder": month_dir,
    }


def safe_read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str).fillna("") if path.exists() else pd.DataFrame()


def safe_read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# =========================
# Upload Section
# =========================
st.subheader("1) Upload Intake File")

uploaded = st.file_uploader("Upload patient intake CSV", type=["csv"])

# Preview + Validation (runs first)
if uploaded is not None:
    st.subheader("2) Preview & Validation")

    try:
        df_preview = pd.read_csv(uploaded, dtype=str).fillna("")
        st.dataframe(df_preview.head(25), use_container_width=True)
        st.info(f"Rows detected: {len(df_preview)}")

        missing_cols, extra_cols = validate_columns(df_preview, REQUIRED_COLUMNS)

        if missing_cols:
            st.error("❌ Missing required columns:")
            st.code("\n".join(missing_cols))
            csv_is_valid = False
        else:
            st.success("✅ All required columns are present.")
            csv_is_valid = True

        if extra_cols:
            with st.expander("Extra columns detected (kept, but not validated)"):
                st.write(extra_cols)

        template_df = pd.DataFrame(columns=REQUIRED_COLUMNS)
        st.download_button(
            "Download CSV Template (Headers Only)",
            data=template_df.to_csv(index=False).encode("utf-8"),
            file_name="patient_intake_template.csv",
            mime="text/csv",
        )

    except Exception as e:
        st.error(f"Could not read CSV: {e}")
        csv_is_valid = False

# Run button (rendered AFTER validation)
st.subheader("3) Run")
run_clicked = st.button(
    "Run Automation",
    type="primary",
    disabled=(uploaded is None or not csv_is_valid),
)



# =========================
# Preview + Validation
# =========================
if uploaded is not None:
    st.subheader("2) Preview & Validation")

    try:
        df_preview = pd.read_csv(uploaded, dtype=str).fillna("")
        st.dataframe(df_preview.head(25), use_container_width=True)
        st.info(f"Rows detected: {len(df_preview)}")

        missing_cols, extra_cols = validate_columns(df_preview, REQUIRED_COLUMNS)

        if missing_cols:
            st.error("❌ Missing required columns:")
            st.code("\n".join(missing_cols))
            csv_is_valid = False
        else:
            st.success("✅ All required columns are present.")
            csv_is_valid = True

        if extra_cols:
            with st.expander("Extra columns detected (kept, but not validated)"):
                st.write(extra_cols)

        # Template download
        template_df = pd.DataFrame(columns=REQUIRED_COLUMNS)
        st.download_button(
            "Download CSV Template (Headers Only)",
            data=template_df.to_csv(index=False).encode("utf-8"),
            file_name="patient_intake_template.csv",
            mime="text/csv",
        )

    except Exception as e:
        st.error(f"Could not read CSV: {e}")
        csv_is_valid = False


# =========================
# Run Automation
# =========================
if run_clicked:
    st.subheader("3) Run")

    incoming_dir = DATA_DIR / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)

    input_path = incoming_dir / uploaded.name
    input_path.write_bytes(uploaded.getvalue())

    with st.spinner("Running eligibility automation..."):
        console_output = run_pipeline(
            input_csv=input_path,
            rules_json=Path(rules_path),
            archive=archive_input,
        )

    st.code(console_output.strip() or "(No console output)", language="text")

    month_dir = find_latest_month(OUTPUTS_DIR)
    files = find_latest_run_files(month_dir) if month_dir else {}

    if not files:
        st.error("Run completed, but output files could not be located.")
    else:
        st.success(f"Run complete. Outputs stored in: {files['folder']}")

        summary = safe_read_json(files["summary"])
        df_results = safe_read_csv(files["results"])
        df_intake = safe_read_csv(files["intake"])
        df_insurance = safe_read_csv(files["insurance"])

        # =========================
        # Summary
        # =========================
        st.subheader("4) Summary")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Records", summary.get("total_records", len(df_results)))
        c2.metric("Approved %", summary.get("percent_approved", "—"))
        c3.metric("Review %", summary.get("percent_review", "—"))
        c4.metric("Rejected %", summary.get("percent_rejected", "—"))

        # =========================
        # Queues
        # =========================
        st.subheader("5) Team Queues")
        q1, q2 = st.columns(2)

        with q1:
            st.markdown("### Intake Queue (Registration)")
            st.dataframe(df_intake, use_container_width=True)

        with q2:
            st.markdown("### Insurance Queue")
            st.dataframe(df_insurance, use_container_width=True)

        # =========================
        # Downloads
        # =========================
        st.subheader("6) Downloads")
        d1, d2, d3, d4 = st.columns(4)

        with d1:
            st.download_button(
                "Results CSV",
                files["results"].read_bytes(),
                files["results"].name,
                "text/csv",
            )
        with d2:
            st.download_button(
                "Intake Queue CSV",
                files["intake"].read_bytes(),
                files["intake"].name,
                "text/csv",
            )
        with d3:
            st.download_button(
                "Insurance Queue CSV",
                files["insurance"].read_bytes(),
                files["insurance"].name,
                "text/csv",
            )
        with d4:
            st.download_button(
                "Summary JSON",
                files["summary"].read_bytes(),
                files["summary"].name,
                "application/json",
            )

        # =========================
        # Audit Log
        # =========================
        st.subheader("7) Audit Log")
        if files["log"].exists():
            st.text_area(
                "Run Log Preview",
                files["log"].read_text(encoding="utf-8")[:6000],
                height=220,
            )
