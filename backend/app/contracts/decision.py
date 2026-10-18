"""Decision and timeline examples match section 6; input wrappers are provisional."""

from datetime import date
from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from .policy import CompiledPolicy, Contract, Money

Verdict = Literal["APPROVE", "NEEDS_REVIEW", "REJECT"]


class DecisionReason(Contract):
    code: str
    effect: Literal["REVIEW", "REJECT", "CAP", "EXCLUDE", "INFO"]
    clause_id: str
    message: str


class Counterfactual(Contract):
    fix: str
    verdict_if_fixed: Verdict
    amount_if_fixed: Money


class LedgerReference(Contract):
    label: str
    cap: Money
    used_before: Money
    used_after: Money


class Decision(Contract):
    receipt_id: str
    verdict: Verdict
    claimed: Money
    proposed: Money
    reimbursable: Money | None
    amount_at_risk: Money
    risk_score: int = Field(ge=0, le=100)
    reasons: list[DecisionReason]
    counterfactuals: list[Counterfactual]
    ledger_refs: list[LedgerReference]
    duplicate_of: str | None

    @model_validator(mode="after")
    def consistent_amounts(self):
        if self.proposed > self.claimed:
            raise ValueError("Proposed amount cannot exceed claim")
        if self.verdict == "NEEDS_REVIEW" and self.reimbursable is not None:
            raise ValueError("Review amount must remain unresolved")
        if self.verdict == "REJECT" and self.reimbursable != 0:
            raise ValueError("Rejected claim must reimburse zero")
        if self.verdict == "APPROVE" and self.reimbursable != self.proposed:
            raise ValueError("Approved amount must equal proposed amount")
        return self


class Employee(Contract):
    id: str
    name: str
    home_city: str


class Submission(Contract):
    receipt_id: str
    employee_id: str
    submitted_at: AwareDatetime
    channel: Literal["email", "upload", "mobile"]
    client_meal: bool = False
    client_name: str | None = None
    attendee_count: int | None = Field(default=None, ge=1)
    attendee_names: list[str] = Field(default_factory=list)
    approved: bool = False


class DuplicateCandidate(Contract):
    receipt_ids: list[str] = Field(min_length=2)
    confirmed: bool


class Period(Contract):
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("Period end precedes start")
        return self


class EvaluationInput(Contract):
    policy: CompiledPolicy
    receipts: list[dict[str, Any]]
    employees: list[Employee]
    candidates: list[DuplicateCandidate]
    submissions: list[Submission]
    period: Period


class LedgerMeter(LedgerReference):
    employee_id: str
    remaining: Money


class Pattern(Contract):
    code: str
    receipt_ids: list[str]
    clause_id: str


class EvaluationResult(Contract):
    decisions: list[Decision]
    ledger_meters: list[LedgerMeter]
    patterns: list[Pattern]
    verdict_counts: dict[Verdict, int] = Field(default_factory=dict)
    amounts: dict[str, Money] = Field(default_factory=dict)


class Flip(Contract):
    receipt_id: str
    from_verdict: Verdict = Field(alias="from")
    to: Verdict
    reason: str


class TimelineEvent(Contract):
    seq: int = Field(ge=1)
    submitted_at: AwareDatetime
    receipt_id: str
    verdict_at_arrival: Verdict
    flips: list[Flip]
