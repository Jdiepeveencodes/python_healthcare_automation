👤 Author

Built by Jesse Diepeveen as a portfolio project demonstrating Python automation, healthcare operations, and API-driven workflows.
___________________________________________________________________________________________________________________________________________________________________________________________

Healthcare Eligibility Automation (Python + API + UI)

A production-style automation pipeline that validates patient intake data, performs insurance eligibility checks, routes work to operational teams, and provides both CLI and UI workflows.

Built to demonstrate:

Healthcare operations knowledge (intake vs insurance workflows)

Python automation & data validation

API integration with fallback behavior

Streamlit UI/UX design

Auditability and reporting best practices

🔍 Problem This Solves

Healthcare intake teams often receive CSV files that:

Contain missing or malformed demographic data

Have incorrect insurance identifiers

Require manual eligibility verification

Get reworked multiple times with no audit trail

This project automates that process by:

Validating intake data

Performing insurance eligibility checks (local rules or API)

Separating issues by intake vs insurance

Generating actionable work queues

Providing a UI for non-technical users

🧠 Key Features

✅ Intake Validation

Required field enforcement

DOB & service date validation

Phone normalization

Clear rejection reasons

🏦 Insurance Eligibility

Local rules engine (payer-specific logic)

Optional API integration (mock FastAPI service)

Automatic fallback if API is unavailable

Full audit visibility (api_used, api_error)

🗂 Work Queue Routing

Intake Queue → Registration / Front Desk

Insurance Queue → Billing / Verification

Priority assignment (HIGH / MEDIUM)

Actionable next steps per record

🖥 User Interfaces

CLI / Batch mode (drag-and-drop supported)

Streamlit UI:

CSV upload

Pre-run validation

API ON/OFF toggle

Results preview

Downloadable outputs

📊 Reporting & Auditability

Timestamped outputs

Monthly folder organization

Run-level logs

Summary statistics (approval %, top issues)


# 🧩 Architecture Diagram

                 ┌────────────────────┐
                 │ patient_intake.csv │
                 └─────────┬──────────┘
                           │
                           ▼
              ┌──────────────────────────┐
              │ Python Eligibility Engine│
              │  - Data Validation       │
              │  - Rule Evaluation       │
              │  - Status Assignment     │
              └─────────┬────────────────┘
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ APPROVED     │ │ REVIEW        │ │ REJECTED     │
│ (No Action)  │ │              │ │              │
└──────────────┘ └──────┬───────┘ └──────┬───────┘
                         │                │
                         ▼                ▼
            ┌───────────────────┐  ┌───────────────────┐
            │ Intake Queue       │  │ Insurance Queue    │
            │ (Registration)     │  │ (Billing / IV)    │
            └─────────┬─────────┘  └─────────┬─────────┘
                      │                      │
                      ▼                      ▼
        outputs/YYYY-MM/intake_queue.csv  outputs/YYYY-MM/insurance_queue.csv

🛠 Technologies Used

Python 3

Pandas

Streamlit

FastAPI (mock service)

Requests

Uvicorn
