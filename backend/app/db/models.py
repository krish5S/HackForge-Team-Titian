from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
)

from app.db.database import Base


class Employee(Base):
    __tablename__ = "employees"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    home_city = Column(String, nullable=True)


class Policy(Base):
    __tablename__ = "policies"

    id = Column(String, primary_key=True)
    version = Column(Integer, nullable=False, default=1)
    source_text = Column(Text, nullable=False)
    clauses_json = Column(JSON, nullable=False, default=list)
    compiled_json = Column(JSON, nullable=False, default=dict)
    trust_report_json = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=False)


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String, primary_key=True)
    employee_id = Column(
        String, ForeignKey("employees.id"), nullable=False, index=True
    )
    channel = Column(String, nullable=False)
    submitted_at = Column(String, nullable=False, index=True)
    file_path = Column(Text, nullable=False)
    employee_fields_json = Column(JSON, nullable=False, default=dict)


class Receipt(Base):
    __tablename__ = "receipts"

    id = Column(String, primary_key=True)
    submission_id = Column(
        String,
        ForeignKey("submissions.id"),
        nullable=False,
        unique=True,
    )
    processed_json = Column(JSON, nullable=False)
    transaction_date = Column(String, nullable=True)
    total_base = Column(String, nullable=True)
    merchant_norm = Column(String, nullable=True)
    card_last4 = Column(String, nullable=True)
    receipt_number = Column(String, nullable=True)
    phash = Column(String, nullable=True)
    risk_score = Column(Integer, nullable=True)


class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"

    receipt_a = Column(
        String, ForeignKey("receipts.id"), primary_key=True
    )
    receipt_b = Column(
        String, ForeignKey("receipts.id"), primary_key=True
    )
    match_type = Column(String, primary_key=True)
    strength = Column(String, nullable=True)
    evidence_json = Column(JSON, nullable=False, default=dict)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id = Column(String, primary_key=True, default=lambda: uuid4().hex)
    policy_id = Column(
        String, ForeignKey("policies.id"), nullable=False
    )
    policy_version = Column(Integer, nullable=False)
    period = Column(String, nullable=False)
    status = Column(String, nullable=False, default="RUNNING")
    created_at = Column(
        String,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )
    summary_json = Column(JSON, nullable=False, default=dict)
    ledger_json = Column(JSON, nullable=False, default=dict)


class Decision(Base):
    __tablename__ = "decisions"

    run_id = Column(
        String, ForeignKey("evaluation_runs.id"), primary_key=True
    )
    receipt_id = Column(
        String, ForeignKey("receipts.id"), primary_key=True
    )
    verdict = Column(String, nullable=False, index=True)
    amounts_json = Column(JSON, nullable=False, default=dict)
    reasons_json = Column(JSON, nullable=False, default=list)
    counterfactuals_json = Column(JSON, nullable=False, default=list)
    ledger_refs_json = Column(JSON, nullable=False, default=list)
    duplicate_of = Column(
        String, ForeignKey("receipts.id"), nullable=True
    )
    risk_score = Column(Integer, nullable=True)