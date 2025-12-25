# Healthcare Intake & Insurance Eligibility Automation (Python)

## Overview
This project is a Python-based healthcare automation that validates patient intake data, performs simulated insurance eligibility checks, and routes issues to the appropriate operational teams (Registration vs Insurance).

The solution is designed to reflect real-world healthcare workflows, emphasizing auditability, data quality, and operational efficiency.

---

## Business Problem
Healthcare organizations frequently experience:
- Claim delays and denials due to intake errors
- Manual eligibility verification taking hours per day
- Lack of clear ownership between intake staff and insurance teams
- Poor audit trails for compliance and reporting

This automation addresses those issues by:
- Catching errors **before** downstream billing
- Routing work to the correct specialty team
- Creating timestamped, auditable batch outputs

---

## Key Features
- ✅ Patient intake validation (DOB, service date, demographics)
- ✅ Insurance eligibility rule engine (payer, member ID, group number)
- ✅ Automated status assignment: APPROVED / REVIEW / REJECTED
- ✅ Siloed work queues:
  - **Intake Queue (Registration team)**
  - **Insurance Queue (Verification/Billing team)**
- ✅ Timestamped outputs (no overwrites)
- ✅ Monthly output folders for audit continuity
- ✅ Human-readable “Next Action” instructions
- ✅ Priority-based routing (HIGH / MEDIUM)
- ✅ Audit log per run

---

## Workflow Summary
1. Intake file is ingested (`patient_intake.csv`)
2. Data is validated and eligibility rules applied
3. Each record is classified:
   - APPROVED → no action
   - REVIEW / REJECTED → routed to correct team
4. Outputs are generated and stored by month and timestamp


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
