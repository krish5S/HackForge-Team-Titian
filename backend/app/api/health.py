from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Receipt

router = APIRouter()


@router.get("/health", tags=["Health"])
def health(db: Session = Depends(get_db)):
    receipt_count = db.scalar(
        select(func.count()).select_from(Receipt)
    )

    return {
        "status": "ok",
        "service": "receipt-graveyard-api",
        "database": "connected",
        "receipt_count": receipt_count,
        "data_loaded": receipt_count > 0,
    }