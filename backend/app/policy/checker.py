"""Non-LLM structural and scope checks for extracted rules."""

from ..contracts.policy import CompilerFlag
from .validate_rules import validate_rules


def check_policy(policy):
    flags = []
    for i, rule in enumerate(policy.rules):
        try:
            validate_rules(policy.model_copy(update={"rules": [rule]}))
        except ValueError as exc:
            flags.append(
                CompilerFlag(
                    code="INVALID_RULE", clause_id=rule.clause_id, message=str(exc)
                )
            )
        for other in policy.rules[:i]:
            if rule.category != other.category:
                continue
            if (
                rule.rule_type == other.rule_type
                and rule.parameters != other.parameters
            ):
                flags.append(
                    CompilerFlag(
                        code="CONFLICT",
                        clause_id=rule.clause_id,
                        message=f"Same scope conflicts with {other.clause_id}.",
                    )
                )
            elif rule.clause_id != other.clause_id and rule.category != "ALL":
                flags.append(
                    CompilerFlag(
                        code="POSSIBLE_EXCEPTION",
                        clause_id=rule.clause_id,
                        message=f"Same category also governed by {other.clause_id}; review interaction.",
                    )
                )
    return flags
