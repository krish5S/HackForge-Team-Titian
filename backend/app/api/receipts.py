from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.api import ReceiptDetail
from app.db.database import PROJECT_ROOT, get_db
from app.db.models import (
    Decision,
    Employee,
    EvaluationRun,
    Receipt,
    ReceiptAsset,
    Submission,
)


router = APIRouter()

RECEIPT_FILES_ROOT = (
    PROJECT_ROOT / "data" / "month" / "images"
).resolve()

SUPPORTED_FILE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
}


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
                "currency": amounts.get("currency"),
                "risk_score": decision.risk_score,
                "reasons": decision.reasons_json or [],
                "counterfactuals": (
                    decision.counterfactuals_json or []
                ),
                "ledger_refs": decision.ledger_refs_json or [],
                "duplicate_of": decision.duplicate_of,
            }

    asset = db.get(ReceiptAsset, receipt_id)
    variants = ["original"]
    if asset and asset.clean_path:
        clean = (PROJECT_ROOT / asset.clean_path).resolve()
        if clean.is_relative_to(RECEIPT_FILES_ROOT) and clean.is_file():
            variants.append("clean")
    return ReceiptDetail(
        available_variants=variants,
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


@router.get(
    "/receipts/{receipt_id}/image",
    response_class=FileResponse,
    tags=["Receipts"],
)
def get_receipt_image(
    receipt_id: str,
    variant: Literal["original", "clean"] = "original",
    db: Session = Depends(get_db),
):
    statement = (
        select(Submission.file_path)
        .select_from(Receipt)
        .join(
            Submission,
            Receipt.submission_id == Submission.id,
        )
        .where(Receipt.id == receipt_id)
    )

    stored_path = db.scalar(statement)

    if stored_path is None:
        raise HTTPException(
            status_code=404,
            detail=f"No receipt {receipt_id}",
        )

    if variant == "clean":
        asset = db.get(ReceiptAsset, receipt_id)
        if not asset or not asset.clean_path:
            raise HTTPException(404, 'Cleaned image is not available for this receipt.')
        stored_path = asset.clean_path

    # The loader will store project-relative paths.
    file_path = (PROJECT_ROOT / stored_path).resolve()

    if not file_path.is_relative_to(RECEIPT_FILES_ROOT):
        raise HTTPException(
            status_code=404,
            detail="Receipt file is outside the receipt directory.",
        )

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Receipt file is missing.",
        )

    media_type = SUPPORTED_FILE_TYPES.get(
        file_path.suffix.lower()
    )

    if media_type is None:
        raise HTTPException(
            status_code=415,
            detail="Unsupported receipt file type.",
        )

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )