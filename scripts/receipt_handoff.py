"""Export/import real worker jobs. No inference runs in an upload HTTP request."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import select
from app.db.database import Base, engine, SessionLocal, PROJECT_ROOT
from app.db.models import ProcessingJob, SubmissionUpload, Submission, Receipt, ReceiptAsset, DuplicateCandidate
from app.db.upload_migration import migrate_uploads
from app.services.loader import save_processed


def export_jobs(db, directory, submission_id=None):
    directory.mkdir(parents=True, exist_ok=True)
    baseline = [row.processed_json for row in db.scalars(select(Receipt))]
    jobs = []
    for upload, sub in db.execute(select(SubmissionUpload, Submission).join(Submission, SubmissionUpload.submission_id == Submission.id)):
        if submission_id is not None and sub.id != submission_id:
            continue
        if db.scalar(select(Receipt.id).where(Receipt.submission_id == sub.id)):
            continue
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.submission_id == sub.id))
        source = (PROJECT_ROOT / sub.file_path).resolve()
        if not source.is_relative_to((PROJECT_ROOT / 'data/month/images').resolve()) or not source.is_file():
            raise ValueError(f'Missing original for submission {sub.id}')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if upload.file_sha256 and upload.file_sha256 != digest:
            raise ValueError('Stored original content changed.')
        if not job:
            job = ProcessingJob(submission_id=sub.id, file_sha256=digest)
            db.add(job)
            db.flush()
        if job.status != 'QUEUED':
            continue
        filename = f'{job.id}{source.suffix}'
        target = directory / filename
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('Existing handoff file differs; choose a new output directory.')
        if not target.exists():
            shutil.copyfile(source, target)
        jobs.append({'job_id': job.id, 'submission_id': sub.id, 'receipt_id': sub.id,
                     'file_sha256': digest, 'image': filename, 'employee_fields': sub.employee_fields_json})
    manifest = {'jobs': jobs, 'baseline_receipts': baseline}
    (directory / 'jobs.json').write_text(json.dumps(manifest, indent=2))
    return len(jobs)


def import_results(db, directory):
    results = json.loads((directory / 'results.json').read_text())
    created = []
    try:
        for result in results['results']:
            job = db.get(ProcessingJob, result['job_id'])
            if not job or job.submission_id != result['submission_id'] or job.file_sha256 != result['file_sha256']:
                raise ValueError('Worker job identity or hash does not match the exported request.')
            if job.status == 'COMPLETED':
                continue
            upload = db.scalar(select(SubmissionUpload).where(SubmissionUpload.submission_id == job.submission_id))
            if result['status'] not in ('COMPLETED', 'FAILED'):
                raise ValueError('Worker result must be COMPLETED or FAILED.')
            if result['status'] == 'FAILED':
                job.status = 'FAILED'
                job.error = 'Receipt processing failed on the worker. Contact the expense team.'
                upload.processing_status, upload.processing_error = 'FAILED', job.error
                continue
            data = result['receipt']
            if data.get('receipt_id') != job.submission_id or data.get('file_sha256') != job.file_sha256:
                raise ValueError('Processed payload ID/hash mismatch.')
            sub = db.get(Submission, job.submission_id)
            save_processed(db, sub, data)
            clean_name = result.get('clean_file')
            if clean_name:
                clean = (directory / clean_name).resolve()
                if not clean.is_relative_to(directory.resolve()) or not clean.is_file():
                    raise ValueError('Invalid worker cleaned file path.')
                from app.api.employee import validate_file
                media_type, suffix = validate_file(clean.read_bytes(), clean.name)
                destination = PROJECT_ROOT / 'data/month/images/uploads' / f'{job.id}-clean{suffix}'
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if destination.read_bytes() != clean.read_bytes():
                        raise ValueError('Conflicting existing cleaned file.')
                else:
                    with destination.open('xb') as target:
                        created.append(destination)
                        target.write(clean.read_bytes())
                db.merge(ReceiptAsset(receipt_id=sub.id, clean_path=destination.relative_to(PROJECT_ROOT).as_posix()))
            job.status, job.error = 'COMPLETED', None
            upload.processing_status, upload.processing_error = 'PROCESSED', None
        db.flush()
        for candidate in results['duplicate_candidates']:
            a, b, kind = candidate['receipt_id'], candidate['duplicate_of'], candidate['reason']
            if not db.get(Receipt, a) or not db.get(Receipt, b) or a == b:
                raise ValueError('Worker duplicate candidate has invalid receipt references.')
            if not db.get(DuplicateCandidate, (a, b, kind)):
                db.add(DuplicateCandidate(receipt_a=a, receipt_b=b, match_type=kind, evidence_json=candidate))
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        for path in created:
            path.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['export', 'import', 'mark-processing', 'retry-failed'])
    parser.add_argument('--directory', type=Path, default=PROJECT_ROOT / 'data/worker-handoff')
    parser.add_argument('--job-id')
    args = parser.parse_args()
    Base.metadata.create_all(engine)
    migrate_uploads(engine)
    with SessionLocal() as db:
        from sqlalchemy import text
        db.execute(text('BEGIN IMMEDIATE'))
        if args.action == 'export':
            print('Exported jobs:', export_jobs(db, args.directory))
            db.commit()
        elif args.action == 'import':
            import_results(db, args.directory)
            print('Worker results imported.')
        else:
            job = db.get(ProcessingJob, args.job_id)
            expected = 'QUEUED' if args.action == 'mark-processing' else 'FAILED'
            if not job or job.status != expected:
                parser.error(f'Job must exist and be {expected}.')
            job.status = 'PROCESSING' if args.action == 'mark-processing' else 'QUEUED'
            upload = db.scalar(select(SubmissionUpload).where(SubmissionUpload.submission_id == job.submission_id))
            upload.processing_status = 'PROCESSING' if args.action == 'mark-processing' else 'UPLOADED'
            upload.processing_error = None
            db.commit()
