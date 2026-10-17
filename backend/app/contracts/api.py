from typing import Literal, Optional

from pydantic import BaseModel


Verdict = Literal["APPROVE", "NEEDS_REVIEW", "REJECT"]


class DecisionRow(BaseModel):
    receipt_id: str
    employee_id: str
    employee_name: str
    merchant_name: Optional[str] = None
    transaction_date: Optional[str] = None
    verdict: Verdict
    claimed: Optional[str] = None
    proposed: Optional[str] = None
    reimbursable: Optional[str] = None
    amount_at_risk: Optional[str] = None
    risk_score: Optional[int] = None
    top_reason: Optional[str] = None


class ReceiptDetail(BaseModel):
    receipt_id: str
    employee_id: str
    employee_name: str
    submission: dict
    processed_receipt: dict
    decision: Optional[dict] = None
    evaluation_run_id: Optional[str] = None