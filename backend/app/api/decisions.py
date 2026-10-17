from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.api import DecisionRow, Verdict
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
    "/decisions",
    response_model=list[DecisionRow],
    tags=["Decisions"],
)
def list_decisions(
    verdict: Optional[Verdict] = None,
    employee_id: Optional[str] = None,
    reason_code: Optional[str] = None,
    db: Session = Depends(get_db),
):
    # Use one completed evaluation for the entire queue.
    latest_run = db.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.status == "COMPLETED")
        .order_by(
            EvaluationRun.created_at.desc(),
            EvaluationRun.id.desc(),
        )
        .limit(1)
    )

    if latest_run is None:
        return []

    statement = (
        select(Decision, Receipt, Submission, Employee)
        .join(Receipt, Decision.receipt_id == Receipt.id)
        .join(Submission, Receipt.submission_id == Submission.id)
        .join(Employee, Submission.employee_id == Employee.id)
        .where(Decision.run_id == latest_run.id)
        .order_by(Receipt.id)
    )

    if verdict is not None:
        statement = statement.where(Decision.verdict == verdict)

    if employee_id is not None:
        statement = statement.where(
            Submission.employee_id == employee_id
        )

    results = []

    for decision, receipt, submission, employee in db.execute(statement):
        reasons = decision.reasons_json or []

        if reason_code is not None:
            if not any(
                reason.get("code") == reason_code
                for reason in reasons
            ):
                continue

        extraction = receipt.processed_json.get("extraction") or {}
        amounts = decision.amounts_json or {}

        results.append(
            DecisionRow(
                receipt_id=receipt.id,
                employee_id=submission.employee_id,
                employee_name=employee.name,
                merchant_name=extraction.get("merchant_name"),
                transaction_date=receipt.transaction_date,
                verdict=decision.verdict,
                claimed=amounts.get("claimed"),
                proposed=amounts.get("proposed"),
                reimbursable=amounts.get("reimbursable"),
                amount_at_risk=amounts.get("amount_at_risk"),
                risk_score=decision.risk_score,
                top_reason=(
                    reasons[0].get("message") if reasons else None
                ),
            )
        )

    # Largest amount at risk first; unknown amounts last.
    results.sort(
        key=lambda row: (
            Decimal(row.amount_at_risk)
            if row.amount_at_risk is not None
            else Decimal("-Infinity")
        ),
        reverse=True,
    )

    return results