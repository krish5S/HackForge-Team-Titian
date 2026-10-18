"""Adapters to Dev 2's pure evaluator. No policy or decision heuristics here."""
import hashlib
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.contracts.decision import EvaluationInput
from app.contracts.policy import CompiledPolicy
from app.db.models import (Decision, DuplicateCandidate, Employee, EvaluationArtifact,
                           EvaluationRun, Policy, Receipt, Submission)
from app.evaluation import evaluate_month, build_timeline


def latest_run(db):
    return db.scalar(select(EvaluationRun).where(EvaluationRun.status == 'COMPLETED')
        .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc()).limit(1))


def active_policy(db):
    policy = db.scalar(select(Policy).where(Policy.is_active.is_(True)).order_by(Policy.version.desc()).limit(1))
    if policy is None:
        raise ValueError('No active policy. Import the supplied month and policy first.')
    return policy


def build_input(db, policy, start, end):
    compiled = CompiledPolicy.model_validate(policy.compiled_json)
    pairs = db.execute(select(Receipt, Submission).join(Submission, Receipt.submission_id == Submission.id)
                       .order_by(Submission.submitted_at, Receipt.id)).all()
    owners = {receipt.id: sub.employee_id for receipt, sub in pairs}
    employees = db.scalars(select(Employee).where(Employee.id.in_(set(owners.values()))).order_by(Employee.id)).all()
    submissions = []
    for receipt, sub in pairs:
        fields = sub.employee_fields_json or {}
        names = fields.get('attendee_names') or []
        if isinstance(names, str):
            names = [name.strip() for name in names.split(',') if name.strip()]
        submissions.append(dict(receipt_id=receipt.id, employee_id=sub.employee_id,
            submitted_at=sub.submitted_at, channel='upload' if sub.channel == 'employee_web' else sub.channel,
            client_meal=fields.get('client_meal', False), client_name=fields.get('client_name') or None,
            attendee_count=fields.get('attendee_count') or None, attendee_names=names,
            approved=fields.get('approved', False) if sub.channel != 'employee_web' else False))
    candidates = []
    for candidate in db.scalars(select(DuplicateCandidate).order_by(DuplicateCandidate.receipt_a, DuplicateCandidate.receipt_b)):
        if candidate.receipt_a in owners and candidate.receipt_b in owners:
            # Dev 1's handoff adapter: same-employee copies confirmed, cross-employee possible.
            candidates.append({'receipt_ids': [candidate.receipt_a, candidate.receipt_b],
                               'confirmed': owners[candidate.receipt_a] == owners[candidate.receipt_b]})
    return EvaluationInput.model_validate(dict(policy=compiled.model_dump(mode='json'),
        receipts=[r.processed_json for r, _ in pairs], submissions=submissions,
        employees=[dict(id=e.id, name=e.name, home_city=e.home_city or '') for e in employees],
        candidates=candidates, period={'start': start, 'end': end}))


def save_evaluation(db, policy, start, end):
    inp = build_input(db, policy, start, end)
    frozen = inp.model_dump(mode='json')
    digest = hashlib.sha256(json.dumps({'input': frozen, 'version': policy.version}, sort_keys=True).encode()).hexdigest()
    previous = db.scalar(select(EvaluationArtifact).where(EvaluationArtifact.input_digest == digest))
    if previous:
        return db.get(EvaluationRun, previous.run_id)
    # Compute everything before publishing. Exceptions leave previous results untouched.
    result = evaluate_month(inp)
    timeline = [event.model_dump(mode='json', by_alias=True) for event in build_timeline(inp)]
    payload = result.model_dump(mode='json')
    run = EvaluationRun(policy_id=policy.id, policy_version=policy.version,
        period=f'{start}/{end}', status='RUNNING', summary_json={
            'currency': inp.policy.base_currency, 'verdict_counts': payload['verdict_counts'],
            'amounts': payload['amounts'], 'patterns': payload['patterns']},
        ledger_json=payload['ledger_meters'])
    db.add(run)
    db.flush()
    for decision in payload['decisions']:
        amounts = {key: decision[key] for key in ('claimed', 'proposed', 'reimbursable', 'amount_at_risk')}
        amounts['currency'] = inp.policy.base_currency
        db.add(Decision(run_id=run.id, receipt_id=decision['receipt_id'], verdict=decision['verdict'],
            amounts_json=amounts, risk_score=decision['risk_score'], reasons_json=decision['reasons'],
            counterfactuals_json=decision['counterfactuals'], ledger_refs_json=decision['ledger_refs'],
            duplicate_of=decision['duplicate_of']))
    db.add(EvaluationArtifact(run_id=run.id, input_digest=digest, input_json=frozen, timeline_json=timeline))
    run.status = 'COMPLETED'
    db.flush()
    return run


def metrics(db, run):
    if run is None:
        return {'run_id': None, 'currency': None, 'evaluated': 0, 'automatically_decided': None,
                'approved_amount': None, 'blocked_amount': None, 'pending_amount': None, 'verdict_counts': {}}
    rows = db.scalars(select(Decision).where(Decision.run_id == run.id)).all()
    def amount(row, field):
        value = (row.amounts_json or {}).get(field)
        return Decimal(value) if value is not None else None
    currencies = {(r.amounts_json or {}).get('currency') for r in rows}
    currency = (run.summary_json or {}).get('currency')
    compatible = not rows or (currency is not None and currencies == {currency})
    approved = [amount(r, 'reimbursable') for r in rows if r.verdict == 'APPROVE']
    blocked = [amount(r, 'amount_at_risk') for r in rows if r.verdict != 'NEEDS_REVIEW']
    pending = [amount(r, 'proposed') for r in rows if r.verdict == 'NEEDS_REVIEW']
    def total(values):
        return format(sum(values, Decimal('0')), '.2f') if compatible and all(v is not None for v in values) else None
    return {'run_id': run.id, 'policy_id': run.policy_id, 'policy_version': run.policy_version,
            'period': run.period, 'currency': currency, 'evaluated': len(rows),
            'automatically_decided': sum(r.verdict != 'NEEDS_REVIEW' for r in rows),
            'approved_amount': total(approved), 'blocked_amount': total(blocked), 'pending_amount': total(pending),
            'verdict_counts': {v: sum(r.verdict == v for r in rows) for v in ('APPROVE', 'NEEDS_REVIEW', 'REJECT')}}
