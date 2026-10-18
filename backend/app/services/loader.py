"""Transactional, repeatable import of the actual Dev 1 month handoff."""
import csv
import hashlib
import json
import re
from pathlib import Path

from sqlalchemy import select
from app.contracts.decision import Employee as EmployeeContract, Submission as SubmissionContract
from app.db.database import PROJECT_ROOT
from app.db.models import Employee, Submission, Receipt, Policy, DuplicateCandidate, ReceiptAsset
from app.policy import load_fallback


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def relative_asset(month, value):
    # Manifest/index paths win over absolute GPU-machine paths. Never traverse out.
    normalized = value.replace('\\', '/')
    if normalized.startswith('/') or (len(normalized) > 1 and normalized[1] == ':'):
        normalized = 'images/' + normalized.rsplit('/', 1)[-1]
    path = (month / normalized).resolve()
    root = (PROJECT_ROOT / 'data/month/images').resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'Original/cleaned file is missing or outside receipt storage: {value}')
    return path.relative_to(PROJECT_ROOT).as_posix()


def save_processed(db, submission, data):
    if not isinstance(data, dict):
        raise ValueError('Processed receipt must be a JSON object.')
    rid = data.get('receipt_id')
    if not isinstance(rid, str) or not rid or not isinstance(data.get('extraction'), dict):
        raise ValueError('Processed receipt requires receipt_id and extraction.')
    if not isinstance(data.get('is_receipt'), bool) or not isinstance(data.get('extraction_status'), str):
        raise ValueError(f'Processed receipt {rid} lacks receipt/extraction status.')
    if any(not isinstance(data.get(key), dict) for key in ('validation', 'fx', 'fingerprints', 'forensics')):
        raise ValueError(f'Processed receipt {rid} has malformed evidence sections.')
    if not isinstance(data.get('file_sha256'), str) or not re.fullmatch(r'[a-fA-F0-9]{64}', data['file_sha256']):
        raise ValueError(f'Processed receipt {rid} has invalid SHA-256.')
    row = db.get(Receipt, rid)
    if row and row.submission_id != submission.id:
        raise ValueError(f'Receipt {rid} already belongs to another submission.')
    if row and row.processed_json != data:
        raise ValueError(f'Conflicting processed receipt {rid}; explicit worker replacement is required.')
    if row:
        return row
    ex, fx, fp, forensic = [data.get(key) or {} for key in ('extraction', 'fx', 'fingerprints', 'forensics')]
    row = Receipt(id=rid, submission_id=submission.id, processed_json=data,
        transaction_date=ex.get('transaction_date') or None, total_base=fx.get('total_base') or None,
        merchant_norm=fp.get('merchant_norm'), card_last4=ex.get('card_last4'), receipt_number=ex.get('receipt_number'),
        phash=fp.get('phash'), risk_score=forensic.get('score'))
    db.add(row)
    db.flush()
    return row


def load_month(db, month, policy_dir):
    month, policy_dir = Path(month).resolve(), Path(policy_dir).resolve()
    with (month / 'employees.csv').open(encoding='utf-8', newline='') as handle:
        employees = list(csv.DictReader(handle))
    with (month / 'manifest.csv').open(encoding='utf-8', newline='') as handle:
        manifest = list(csv.DictReader(handle))
    employee_keys = {'id', 'name', 'home_city'}
    manifest_keys = {'receipt_id', 'employee_id', 'image_path', 'submitted_at', 'channel', 'client_meal', 'client_name', 'attendee_count', 'attendee_names', 'approved'}
    if any(not employee_keys.issubset(row) for row in employees) or any(not manifest_keys.issubset(row) for row in manifest):
        raise ValueError('Employee or manifest CSV is missing required contract columns.')
    if len({r['id'] for r in employees}) != len(employees) or len({r['receipt_id'] for r in manifest}) != len(manifest):
        raise ValueError('Duplicate employee or receipt identifiers in import.')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', row['id']) for row in employees) or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', row['receipt_id']) for row in manifest):
        raise ValueError('Employee and receipt identifiers must be safe, nonempty IDs.')
    for raw in employees:
        data = EmployeeContract.model_validate(raw)
        row = db.get(Employee, data.id)
        if row and (row.name != data.name or (row.home_city or '') != data.home_city):
            raise ValueError(f'Employee identity conflict for {data.id}; existing identity/account links were not changed.')
        if not row:
            db.add(Employee(**data.model_dump()))
    db.flush()
    for raw in manifest:
        fields = {key: raw.get(key) for key in ('client_name',)}
        for key in ('client_meal', 'approved'):
            if raw[key] not in ('true', 'false'):
                raise ValueError(f'Invalid {key} in {raw["receipt_id"]}')
            fields[key] = raw[key] == 'true'
        fields['attendee_count'] = int(raw['attendee_count']) if raw['attendee_count'] else None
        fields['attendee_names'] = json.loads(raw['attendee_names'] or '[]')
        fields['client_name'] = fields['client_name'] or None
        contract = SubmissionContract.model_validate({**fields, **{k: raw[k] for k in ('receipt_id','employee_id','submitted_at','channel')}})
        if not db.get(Employee, contract.employee_id):
            raise ValueError(f'Unknown employee for {contract.receipt_id}')
        file_path = relative_asset(month, raw['image_path'])
        data = read_json(month / 'processed' / f'{contract.receipt_id}.json')
        if not isinstance(data, dict) or data.get('receipt_id') != contract.receipt_id:
            raise ValueError('Processed receipt ID does not match manifest.')
        digest = hashlib.sha256((PROJECT_ROOT / file_path).read_bytes()).hexdigest()
        if data.get('file_sha256') != digest:
            raise ValueError(f'Original file hash mismatch for {contract.receipt_id}')
        row = db.get(Submission, contract.receipt_id)
        values = dict(employee_id=contract.employee_id, channel=contract.channel,
                      submitted_at=raw['submitted_at'], file_path=file_path, employee_fields_json=fields)
        if row and any(getattr(row, key) != value for key, value in values.items()):
            raise ValueError(f'Submission conflict for {contract.receipt_id}; no records overwritten.')
        if not row:
            row = Submission(id=contract.receipt_id, **values)
            db.add(row)
            db.flush()
        save_processed(db, row, data)
        clean = raw.get('clean_path') or data.get('clean_path')
        if clean:
            normalized = relative_asset(month, clean)
            asset = db.get(ReceiptAsset, contract.receipt_id)
            if asset and asset.clean_path != normalized:
                raise ValueError('Conflicting cleaned file reference.')
            if not asset:
                db.add(ReceiptAsset(receipt_id=contract.receipt_id, clean_path=normalized))
    candidates = read_json(month / 'processed/duplicate_candidates.json')
    if not isinstance(candidates, list):
        raise ValueError('Duplicate candidates must be a JSON array.')
    for raw in candidates:
        if not isinstance(raw, dict) or not {'receipt_id', 'duplicate_of', 'reason'}.issubset(raw):
            raise ValueError('Malformed duplicate candidate.')
        first, second = raw['receipt_id'], raw['duplicate_of']
        if first == second or not db.get(Receipt, first) or not db.get(Receipt, second):
            raise ValueError('Duplicate candidate references an unknown receipt or itself.')
        key = (first, second, raw['reason'])
        if not db.get(DuplicateCandidate, key):
            db.add(DuplicateCandidate(receipt_a=first, receipt_b=second, match_type=raw['reason'], evidence_json=raw))
    policy = load_fallback(policy_dir / 'fallback_rules.json')
    source = (policy_dir / 'policy.md').read_text(encoding='utf-8')
    existing = db.get(Policy, policy.policy_id)
    if existing and (existing.compiled_json != policy.model_dump(mode='json') or existing.source_text != source):
        raise ValueError('Policy import conflicts with an existing policy version.')
    if not existing:
        has_active = db.scalar(select(Policy.id).where(Policy.is_active.is_(True)).limit(1))
        db.add(Policy(id=policy.policy_id, source_text=source, clauses_json=[c.model_dump() for c in policy.clauses],
            compiled_json=policy.model_dump(mode='json'), trust_report_json=read_json(policy_dir / 'compiled.json'),
            is_active=has_active is None))
    db.flush()
    return {'employees': len(employees), 'submissions': len(manifest), 'policy_id': policy.policy_id}
