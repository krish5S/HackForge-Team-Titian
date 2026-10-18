"""Dev 2 provisional policy contract; see data/policy/IMPLEMENTATION.md."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer


def parse_money(value: str | Decimal) -> Decimal:
    if not isinstance(value, (str, Decimal)):
        raise ValueError("Money must be a decimal string or Decimal, never float")
    try:
        result = Decimal(value)
    except Exception as exc:
        raise ValueError("Invalid decimal amount") from exc
    if (
        not result.is_finite()
        or result < 0
        or result != result.quantize(Decimal(".01"))
    ):
        raise ValueError("Money must be finite, nonnegative and cent precise")
    return result


Money = Annotated[
    Decimal,
    BeforeValidator(parse_money, json_schema_input_type=str),
    PlainSerializer(lambda v: format(v, ".2f"), return_type=str, when_used="json"),
]


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class Clause(Contract):
    clause_id: str
    text: str = Field(min_length=1)


RuleType = Literal[
    "MONTHLY_CAP",
    "CITY_DAILY_CAP",
    "LOCAL_MEAL",
    "EXCLUDE_ITEMS",
    "CLIENT_DETAILS",
    "APPROVAL_THRESHOLD",
    "ITEMIZATION",
    "TIP_LIMIT",
    "SUBMISSION_DEADLINE",
    "EVIDENCE_REVIEW",
]


class RuleParameters(Contract):
    amount: Money | None = None
    cities: dict[str, Money] | None = None
    item_classes: list[str] | None = None
    fraction: Decimal | None = None
    days: int | None = Field(default=None, ge=0)
    risk_threshold: int | None = Field(default=None, ge=0, le=100)


class Rule(Contract):
    rule_type: RuleType
    clause_id: str
    source_quote: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    category: Literal["ALL", "MEALS", "ENTERTAINMENT", "TRAVEL", "LODGING", "OFFICE"]
    parameters: RuleParameters


class CompiledPolicy(Contract):
    policy_id: str
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    clauses: list[Clause]
    rules: list[Rule]


class CompilerFlag(Contract):
    code: str
    clause_id: str | None
    message: str


class CheckResult(Contract):
    status: Literal["PASSED", "FAILED", "NOT_RUN"]
    checked: int = Field(ge=0)
    failed: int = Field(ge=0)
    detail: str


class TrustReport(Contract):
    coverage: CheckResult
    grounding: CheckResult
    agreement: CheckResult
    checker: CheckResult
    boundary: CheckResult


class CompileResult(Contract):
    policy: CompiledPolicy | None
    flags: list[CompilerFlag]
    trust_report: TrustReport
