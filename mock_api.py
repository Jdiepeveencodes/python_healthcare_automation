from __future__ import annotations

import re
from datetime import date
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Mock Insurance Eligibility API", version="1.0")


SUPPORTED_PAYERS = {"Kaiser", "Aetna", "BlueCross", "United", "SelfPay"}


class EligibilityRequest(BaseModel):
    insurance_provider: str
    member_id: str | None = None
    member_group: str | None = None
    dob: str | None = None
    service_date: str | None = None


@app.post("/eligibility")
def check_eligibility(req: EligibilityRequest):
    reasons: list[str] = []

    payer = (req.insurance_provider or "").strip()
    member_id = (req.member_id or "").strip()
    member_group = (req.member_group or "").strip()

    if not payer:
        reasons.append("MISSING_INSURANCE_PROVIDER")
    elif payer not in SUPPORTED_PAYERS:
        reasons.append("PAYER_NOT_SUPPORTED")

    if payer and payer != "SelfPay":
        if not member_id:
            reasons.append("MISSING_MEMBER_ID")
        elif not re.match(r"^ID-\d{10}$", member_id):
            reasons.append("MEMBER_ID_INVALID_FORMAT")

        if not member_group:
            reasons.append("MISSING_MEMBER_GROUP")
        elif not re.match(r"^G-\d{6,9}$", member_group):
            reasons.append("MEMBER_GROUP_INVALID_FORMAT")

    # “API-style” status decision
    if any(r.startswith("MISSING_") for r in reasons):
        status = "REJECTED"
    elif reasons:
        status = "REVIEW"
    else:
        status = "APPROVED"

    return {
        "status": status,
        "reasons": reasons,
        "payer": payer,
        "plan": "MOCK-HMO",
        "effective_date": str(date.today().replace(month=1, day=1)),
        "termination_date": None,
        "reference_id": f"MOCK-{member_id or 'SELF'}",
    }
