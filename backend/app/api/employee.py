"""Employee-owned submissions. Uploading does not perform receipt evaluation."""
import hashlib
import io
import json
import os
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.auth import require_employee, validate_origin
from app.db.database import PROJECT_ROOT, get_db
from app.db.models import AuthUser, Decision, EvaluationRun, Receipt, Submission, SubmissionUpload

router = APIRouter(prefix='/employee/submissions', tags=['Employee submissions'])
UPLOAD_ROOT = PROJECT_ROOT / 'data' / 'month' / 'images' / 'uploads'
MAX_FILE_BYTES = 10 * 1024 * 1024
TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.pdf': 'application/pdf'}


def owned(db, employee_id, submission_id):
    row = db.scalar(select(Submission).where(Submission.id == submission_id, Submission.employee_id == employee_id))
    if row is None:
        raise HTTPException(404, 'Submission not found.')
    return row


def serialize(db, submission):
    upload = db.scalar(select(SubmissionUpload).where(SubmissionUpload.submission_id == submission.id))
    receipt = db.scalar(select(Receipt).where(Receipt.submission_id == submission.id))
    decision = None
    latest_run = db.scalar(select(EvaluationRun).where(EvaluationRun.status == 'COMPLETED')
        .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc()).limit(1))
    if receipt and latest_run:
        decision = db.get(Decision, (latest_run.id, receipt.id))
    processing = upload.processing_status if upload else 'UPLOADED'
    if receipt and processing not in ('PROCESSING', 'FAILED'):
        processing = 'PROCESSED'
    result = None if decision is None else {
        'verdict': decision.verdict, 'amounts': {key: (decision.amounts_json or {}).get(key)
            for key in ('claimed', 'proposed', 'reimbursable', 'amount_at_risk', 'currency')},
        'reasons': decision.reasons_json or [], 'counterfactuals': decision.counterfactuals_json or [],
    }
    return {
        'id': submission.id, 'submitted_at': submission.submitted_at,
        'fields': submission.employee_fields_json or {},
        'filename': upload.original_name if upload else Path(submission.file_path).name,
        'size_bytes': upload.size_bytes if upload else None,
        'media_type': upload.media_type if upload else TYPES.get(Path(submission.file_path).suffix.lower()),
        'status': 'EVALUATED' if decision else processing,
        'processing_status': processing,
        'processing_error': upload.processing_error if upload and processing == 'FAILED' else None,
        'receipt_id': receipt.id if receipt else None, 'decision': result,
    }


def validate_file(content, filename):
    suffix = Path(filename).suffix.lower()
    media_type = TYPES.get(suffix)
    if not media_type:
        raise HTTPException(415, 'Use a JPEG, PNG, WebP, or PDF file.')
    try:
        if media_type == 'application/pdf':
            if not content.startswith(b'%PDF-'):
                raise ValueError()
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted or len(reader.pages) == 0:
                raise ValueError()
        else:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    if Image.MIME.get(image.format) != media_type:
                        raise ValueError()
                    image.verify()
    except Exception as exc:
        # No parser exception text (which can contain file contents) is exposed.
        raise HTTPException(422, 'The receipt file is invalid, encrypted, or does not match its extension.') from exc
    return media_type, suffix


@router.post('', status_code=201, dependencies=[Depends(validate_origin)])
async def submit(request: Request, user: AuthUser = Depends(require_employee), db: Session = Depends(get_db)):
    key = request.headers.get('idempotency-key', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', key):
        raise HTTPException(422, 'A valid Idempotency-Key header is required.')
    raw_key = key
    key = hashlib.sha256(f'{user.id}:{raw_key}'.encode()).hexdigest()
    async with request.form(max_files=1, max_fields=6, max_part_size=16 * 1024) as form:
        allowed = {'file', 'purpose', 'client_name', 'attendee_names', 'attendee_count', 'notes', 'client_meal'}
        if set(form) - allowed or len(form.multi_items()) != len(form):
            raise HTTPException(422, 'Unexpected or repeated submission fields.')
        file = form.get('file')
        if not isinstance(file, UploadFile):
            raise HTTPException(422, 'Select one receipt file.')
        fields = {}
        for name, limit in [('purpose', 1000), ('client_name', 300), ('attendee_names', 2000), ('notes', 5000)]:
            value = form.get(name, '')
            if not isinstance(value, str) or len(value) > limit:
                raise HTTPException(422, f'Invalid {name.replace("_", " ")}.')
            fields[name] = value.strip()
        if not fields['purpose']:
            raise HTTPException(422, 'Expense purpose is required.')
        client_meal = form.get('client_meal')
        if client_meal is not None:
            if client_meal not in ('true', 'false'):
                raise HTTPException(422, 'Client meal must be true or false.')
            fields['client_meal'] = client_meal == 'true'
        count = form.get('attendee_count', '')
        if not isinstance(count, str) or (count and (not re.fullmatch(r'\d{1,5}', count) or int(count) > 10000)):
            raise HTTPException(422, 'Attendee count must be a whole number from 0 to 10000.')
        fields['attendee_count'] = int(count) if count else None
        content = await file.read(MAX_FILE_BYTES + 1)
        filename = (file.filename or 'receipt').replace('\\', '/').split('/')[-1]
        if not content or len(content) > MAX_FILE_BYTES:
            raise HTTPException(413, 'Select a nonempty receipt no larger than 10 MiB.')
        fingerprint = hashlib.sha256(content + json.dumps({'fields': fields, 'filename': filename}, sort_keys=True).encode()).hexdigest()
        prior = db.get(SubmissionUpload, (user.employee_id, key))
        if prior is None:
            legacy = db.get(SubmissionUpload, (user.employee_id, raw_key))
            if legacy and legacy.user_id is None:
                raise HTTPException(409, 'This legacy retry cannot be attributed to one account. Check your history before starting a new submission.')
            if legacy and legacy.user_id == user.id:
                prior = legacy
        if prior:
            if prior.request_hash != fingerprint:
                raise HTTPException(409, 'This retry key belongs to different submission content.')
            return serialize(db, owned(db, user.employee_id, prior.submission_id))
        media_type, suffix = validate_file(content, filename)
        submission_id = uuid4().hex
        path = UPLOAD_ROOT / f'{submission_id}{suffix}'
        created_file = False
        try:
            UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
            # The complete file is durable before committing its database reference.
            with path.open('xb') as target:
                created_file = True
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            submission = Submission(id=submission_id, employee_id=user.employee_id, channel='employee_web',
                submitted_at=datetime.now(timezone.utc).isoformat(), file_path=str(path.relative_to(PROJECT_ROOT)),
                employee_fields_json=fields)
            db.add(submission)
            db.flush()
            db.add(SubmissionUpload(employee_id=user.employee_id, idempotency_key=key, submission_id=submission_id,
                request_hash=fingerprint, original_name=filename, media_type=media_type, size_bytes=len(content),
                user_id=user.id, file_sha256=hashlib.sha256(content).hexdigest(), processing_status='UPLOADED'))
            db.commit()
        except IntegrityError:
            db.rollback()
            if created_file:
                path.unlink(missing_ok=True)
            prior = db.get(SubmissionUpload, (user.employee_id, key))
            if prior and prior.request_hash == fingerprint:
                return serialize(db, owned(db, user.employee_id, prior.submission_id))
            raise HTTPException(409, 'The submission key is already in use. Retry the original submission.')
        except Exception as exc:
            db.rollback()
            if created_file:
                path.unlink(missing_ok=True)
            raise HTTPException(503, 'The receipt could not be saved. Retry with the same submission key.') from exc
        return serialize(db, submission)


@router.get('')
def history(user: AuthUser = Depends(require_employee), db: Session = Depends(get_db)):
    rows = db.scalars(select(Submission).where(Submission.employee_id == user.employee_id)
        .order_by(Submission.submitted_at.desc(), Submission.id.desc())).all()
    return [serialize(db, row) for row in rows]


@router.get('/{submission_id}')
def detail(submission_id: str, user: AuthUser = Depends(require_employee), db: Session = Depends(get_db)):
    return serialize(db, owned(db, user.employee_id, submission_id))


@router.get('/{submission_id}/file')
def original_file(submission_id: str, user: AuthUser = Depends(require_employee), db: Session = Depends(get_db)):
    submission = owned(db, user.employee_id, submission_id)
    path = (PROJECT_ROOT / submission.file_path).resolve()
    root = (PROJECT_ROOT / 'data' / 'month' / 'images').resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, 'Receipt file unavailable.')
    media_type = TYPES.get(path.suffix.lower())
    if not media_type:
        raise HTTPException(415, 'Receipt file type unavailable.')
    return FileResponse(path, media_type=media_type, headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "sandbox", 'Content-Disposition': 'inline',
    })
