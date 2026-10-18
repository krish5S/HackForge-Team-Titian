"""Reviewer orchestration over saved inputs and the real teammate engines."""
import csv
import io
from datetime import date, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select, update, text
from sqlalchemy.orm import Session

from app.auth import validate_origin
from app.db.database import get_db
from app.db.models import Decision, Employee, EvaluationArtifact, EvaluationRun, Policy, PolicyCompilation, Receipt, Submission
from app.evaluation import evaluate_month
from app.policy import compile_policy
from app.services.evaluations import active_policy, latest_run, save_evaluation, metrics

router = APIRouter()


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start: date | None = None
    end: date | None = None

    @model_validator(mode='after')
    def valid_period(self):
        if (self.start is None) != (self.end is None) or (self.start and self.end < self.start):
            raise ValueError('Supply an ordered start and end together.')
        return self


class CompileRequest(EvaluateRequest):
    activate: bool = True


def period(db, body):
    if body.start:
        return body.start.isoformat(), body.end.isoformat()
    previous = latest_run(db)
    if previous:
        parts = previous.period.split('/')
        if len(parts) == 2:
            return tuple(parts)
    days = []
    for receipt, submitted in db.execute(select(Receipt, Submission.submitted_at).join(Submission, Receipt.submission_id == Submission.id)):
        for value in [receipt.transaction_date, submitted[:10]]:
            try:
                days.append(date.fromisoformat(value))
            except (TypeError, ValueError):
                pass
    if not days:
        raise HTTPException(409, 'No processed receipts are available to evaluate.')
    return min(days).isoformat(), max(days).isoformat()


def run_json(run):
    return {'run_id': run.id, 'policy_id': run.policy_id, 'policy_version': run.policy_version, 'period': run.period, 'status': run.status}


@router.get('/policies/active')
def get_policy(db: Session = Depends(get_db)):
    try:
        policy = active_policy(db)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    attempt = db.scalar(select(PolicyCompilation).where(PolicyCompilation.policy_id == policy.id)
                        .order_by(PolicyCompilation.created_at.desc()).limit(1))
    return {'id': policy.id, 'version': policy.version, 'source_text': policy.source_text,
            'compiled': policy.compiled_json, 'trust_report': policy.trust_report_json,
            'latest_compilation': attempt.result_json if attempt else None}


@router.post('/policies/{policy_id}/compile', dependencies=[Depends(validate_origin)])
def compile_active(policy_id: str, body: CompileRequest, db: Session = Depends(get_db)):
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(404, 'Policy not found.')
    source, version = policy.source_text, policy.version
    db.rollback()  # No database write lock during external model calls.
    result = compile_policy(source)
    report = result.model_dump(mode='json')
    db.execute(text('BEGIN IMMEDIATE'))
    try:
        policy = db.get(Policy, policy_id)
        if policy.source_text != source or policy.version != version:
            raise HTTPException(409, 'Policy changed during compilation; retry.')
        db.add(PolicyCompilation(policy_id=policy_id, result_json=report))
        activated, run = False, None
        if body.activate and result.policy is not None:
            if not policy.is_active:
                raise HTTPException(409, 'Only the current active policy can be replaced.')
            start, end = period(db, body)
            next_id = f'{policy_id}-v{version + 1}-{uuid4().hex[:8]}'
            compiled = result.policy.model_copy(update={'policy_id': next_id})
            new_policy = Policy(id=next_id, version=version + 1, source_text=source,
                clauses_json=[c.model_dump() for c in compiled.clauses], compiled_json=compiled.model_dump(mode='json'),
                trust_report_json=report, is_active=False)
            db.add(new_policy)
            db.flush()
            run = save_evaluation(db, new_policy, start, end)
            db.execute(update(Policy).values(is_active=False))
            new_policy.is_active = True
            activated = True
        db.commit()
        return {'activated': activated, 'result': report, 'evaluation': run_json(run) if run else None}
    except HTTPException:
        db.rollback()
        raise
    except (ValueError, ArithmeticError) as exc:
        db.rollback()
        raise HTTPException(422, f'Compiled policy could not be evaluated: {exc}')
    except Exception:
        db.rollback()
        raise HTTPException(503, 'Policy activation failed; the previous policy and results were preserved.')


@router.post('/evaluations', dependencies=[Depends(validate_origin)])
def evaluate(body: EvaluateRequest, db: Session = Depends(get_db)):
    db.execute(text('BEGIN IMMEDIATE'))
    try:
        start, end = period(db, body)
        run = save_evaluation(db, active_policy(db), start, end)
        db.commit()
        return run_json(run)
    except HTTPException:
        db.rollback()
        raise
    except (ValueError, ArithmeticError) as exc:
        db.rollback()
        raise HTTPException(422, f'Evaluation input is invalid: {exc}')
    except Exception:
        db.rollback()
        raise HTTPException(503, 'Evaluation failed; previous completed results remain available.')


@router.get('/metrics')
def get_metrics(db: Session = Depends(get_db)):
    return metrics(db, latest_run(db))


def artifact(db, run_id=None):
    run = db.get(EvaluationRun, run_id) if run_id else latest_run(db)
    if run_id and (run is None or run.status != 'COMPLETED'):
        raise HTTPException(404, 'Completed evaluation not found.')
    if run is None:
        return None, None
    saved = db.get(EvaluationArtifact, run.id)
    if saved is None:
        raise HTTPException(409, 'This legacy run has no frozen input. Run a new evaluation to enable replay.')
    return run, saved


@router.get('/timeline')
def timeline(db: Session = Depends(get_db)):
    run, saved = artifact(db)
    return {'run_id': run.id if run else None, 'policy_version': run.policy_version if run else None,
            'events': saved.timeline_json if saved else []}


@router.get('/replay')
def replay(as_of: datetime = Query(...), run_id: str | None = None, db: Session = Depends(get_db)):
    if as_of.utcoffset() is None:
        raise HTTPException(422, 'as_of must include a timezone.')
    run, saved = artifact(db, run_id)
    if not saved:
        return {'run_id': None, 'snapshot': None, 'currency': None}
    result = evaluate_month(saved.input_json, as_of=as_of)
    return {'run_id': run.id, 'policy_version': run.policy_version, 'as_of': as_of.isoformat(),
            'currency': saved.input_json['policy']['base_currency'], 'snapshot': result.model_dump(mode='json')}


def csv_cell(value):
    value = '' if value is None else str(value)
    # Protect untrusted names/reasons and any leading whitespace before formulas.
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


@router.get('/exports/decisions')
def export(db: Session = Depends(get_db)):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['run_id','policy_id','policy_version','receipt_id','employee','merchant','verdict','claimed','proposed','reimbursable','amount_at_risk','currency','reason'])
    run = latest_run(db)
    if run:
        rows = db.execute(select(Decision, Receipt, Employee).join(Receipt, Decision.receipt_id == Receipt.id)
            .join(Submission, Receipt.submission_id == Submission.id).join(Employee, Submission.employee_id == Employee.id)
            .where(Decision.run_id == run.id).order_by(Receipt.id)).all()
        for d, r, employee in rows:
            a = d.amounts_json or {}
            writer.writerow([csv_cell(value) for value in [run.id, run.policy_id, run.policy_version, r.id,
                employee.name, (r.processed_json.get('extraction') or {}).get('merchant_name'), d.verdict,
                a.get('claimed'), a.get('proposed'), a.get('reimbursable'), a.get('amount_at_risk'), a.get('currency'),
                '; '.join(reason.get('message', '') for reason in (d.reasons_json or []))]])
    return Response(stream.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="decisions.csv"', 'Cache-Control': 'no-store'})
