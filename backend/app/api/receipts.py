from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.api import ReceiptDetail
from app.db.database import get_db
from app.db.models import (
    Decision,
    Employee,
    EvaluationRun,
    Receipt,
    Submission,
)


router = APIRouter()


@router.get(
    "/receipts/{receipt_id}",
    response_model=ReceiptDetail,
    tags=["Receipts"],
)
def get_receipt(
    receipt_id: str,
    db: Session = Depends(get_db),
):
    statement = (
        select(Receipt, Submission, Employee)
        .join(
            Submission,
            Receipt.submission_id == Submission.id,
        )
        .join(
            Employee,
            Submission.employee_id == Employee.id,
        )
        .where(Receipt.id == receipt_id)
    )

    record = db.execute(statement).first()

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No receipt {receipt_id}",
        )

    receipt, submission, employee = record

    latest_run = db.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.status == "COMPLETED")
        .order_by(
            EvaluationRun.created_at.desc(),
            EvaluationRun.id.desc(),
        )
        .limit(1)
    )

    decision_payload = None

    if latest_run is not None:
        decision = db.get(
            Decision,
            (latest_run.id, receipt_id),
        )

        if decision is not None:
            amounts = decision.amounts_json or {}

            decision_payload = {
                "receipt_id": receipt.id,
                "verdict": decision.verdict,
                "claimed": amounts.get("claimed"),
                "proposed": amounts.get("proposed"),
                "reimbursable": amounts.get("reimbursable"),
                "amount_at_risk": amounts.get("amount_at_risk"),
                "risk_score": decision.risk_score,
                "reasons": decision.reasons_json or [],
                "counterfactuals": (
                    decision.counterfactuals_json or []
                ),
                "ledger_refs": decision.ledger_refs_json or [],
                "duplicate_of": decision.duplicate_of,
            }

    return ReceiptDetail(
        receipt_id=receipt.id,
        employee_id=employee.id,
        employee_name=employee.name,
        submission={
            "id": submission.id,
            "channel": submission.channel,
            "submitted_at": submission.submitted_at,
            "employee_fields": (
                submission.employee_fields_json or {}
            ),
        },
        processed_receipt=receipt.processed_json,
        decision=decision_payload,
        evaluation_run_id=(
            latest_run.id
            if latest_run is not None
            else None
        ),
    )