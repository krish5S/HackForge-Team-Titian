"""Single local background worker: existing handoff -> real pipeline -> saved evaluation."""
import argparse
from datetime import date
import fcntl
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
from dotenv import load_dotenv
from sqlalchemy import select, text
from app.db.database import Base, SessionLocal, engine
from app.db.models import ProcessingJob, Receipt, Submission, SubmissionUpload
from app.db.upload_migration import migrate_uploads
from app.services.evaluations import active_policy, latest_run, save_evaluation
from scripts.receipt_handoff import export_jobs, import_results

LOG = logging.getLogger('receipt-worker')


def evaluate_processed(db):
    """Cumulative live scope includes new dates; never replace the active policy."""
    days = []
    previous = latest_run(db)
    if previous:
        days.extend(date.fromisoformat(day) for day in previous.period.split('/'))
    for receipt, submitted in db.execute(select(Receipt, Submission.submitted_at).join(
            Submission, Receipt.submission_id == Submission.id)):
        for value in (receipt.transaction_date, submitted[:10]):
            try:
                days.append(date.fromisoformat(value))
            except (TypeError, ValueError):
                pass
    if not days:
        return None
    return save_evaluation(db, active_policy(db), min(days).isoformat(), max(days).isoformat())


def cycle(root, lock_fd, runner=subprocess.run):
    """Durable active bundle supports restart without resubmitting or repeating completed work."""
    marker = root / 'active.json'
    if marker.exists():
        directory = root / json.loads(marker.read_text())['bundle']
        if directory.parent.resolve() != root.resolve():
            raise ValueError('Invalid local worker bundle')
    else:
        with SessionLocal() as db:
            pending = db.scalar(select(SubmissionUpload.submission_id).outerjoin(
                Receipt, Receipt.submission_id == SubmissionUpload.submission_id).outerjoin(
                ProcessingJob, ProcessingJob.submission_id == SubmissionUpload.submission_id).where(
                Receipt.id.is_(None),
                (ProcessingJob.id.is_(None)) | (ProcessingJob.status == 'QUEUED')).limit(1))
            if not pending:
                return False
        directory = root / uuid4().hex
        directory.mkdir()
        temporary = marker.with_suffix('.tmp')
        temporary.write_text(json.dumps({'bundle': directory.name}))
        temporary.replace(marker)
        with SessionLocal() as db:
            db.execute(text('BEGIN IMMEDIATE'))
            export_jobs(db, directory, submission_id=pending)
            db.commit()
    if not (directory / 'jobs.json').exists():
        # Crash before the export transaction; no work was claimed.
        marker.unlink()
        return True
    manifest = json.loads((directory / 'jobs.json').read_text())
    with SessionLocal() as db:
        if any(db.get(ProcessingJob, item['job_id']) is None for item in manifest['jobs']):
            # Crash after writing the manifest but before committing job reservations.
            marker.unlink()
            return True
    if not manifest['jobs']:
        marker.unlink()
        return True
    if not (directory / 'results.json').exists():
        with SessionLocal() as db:
            db.execute(text('BEGIN IMMEDIATE'))
            for item in manifest['jobs']:
                job = db.get(ProcessingJob, item['job_id'])
                if not job or job.status not in {'QUEUED', 'PROCESSING'}:
                    raise ValueError('Local worker job state changed')
                job.status = 'PROCESSING'
                upload = db.scalar(select(SubmissionUpload).where(SubmissionUpload.submission_id == job.submission_id))
                upload.processing_status, upload.processing_error = 'PROCESSING', None
            db.commit()
        # Our flock is inherited by the child, so restart cannot race a surviving child.
        stale = directory / '.worker-lock'
        if stale.exists():
            stale.rmdir()
        LOG.info('Processing bundle %s', directory.name)
        try:
            result = runner([sys.executable, '-m', 'scripts.run_receipt_worker', '--directory', str(directory)],
                            cwd=ROOT, pass_fds=(lock_fd,), timeout=600)
            failed = result.returncode != 0
        except subprocess.TimeoutExpired:
            failed = True
        if failed and not (directory / 'results.json').exists():
            failures = [{**{k: item[k] for k in ('job_id', 'submission_id', 'file_sha256')},
                         'status': 'FAILED'} for item in manifest['jobs']]
            (directory / 'results.json').write_text(json.dumps({'results': failures, 'duplicate_candidates': []}))
    with SessionLocal() as db:
        db.execute(text('BEGIN IMMEDIATE'))
        import_results(db, directory)
    # A failed evaluation leaves PROCESSED data saved and the prior completed run usable.
    # Keep the marker so restart retries evaluation, not inference.
    with SessionLocal() as db:
        db.execute(text('BEGIN IMMEDIATE'))
        run = evaluate_processed(db)
        db.commit()
        LOG.info('Results saved; evaluation %s', run.id if run else 'unavailable')
    marker.unlink()
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--interval', type=float, default=5)
    args = parser.parse_args()
    if args.interval < 1:
        parser.error('interval must be at least one second')
    load_dotenv(ROOT / 'backend/.env', override=False)
    # Keep all downloaded inference caches inside ignored project data.
    os.environ.setdefault('PADDLE_PDX_CACHE_HOME', str(ROOT / 'data/model-cache/paddlex'))
    os.environ.setdefault('PADDLE_HOME', str(ROOT / 'data/model-cache/paddle'))
    os.environ.setdefault('HF_HOME', str(ROOT / 'data/model-cache/huggingface'))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    root = ROOT / 'data/local-worker'
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.error('Another local worker is running.')
            return 1
        # Verify imports before claiming uploads; missing dependencies leave them pending.
        try:
            from backend.app.pipeline.process import process_receipt  # noqa: F401
        except ImportError:
            LOG.error('Worker dependencies unavailable. Install backend/requirements/worker.txt.')
            return 1
        Base.metadata.create_all(engine)
        migrate_uploads(engine)
        LOG.info('Local receipt worker ready.')
        while True:
            try:
                cycle(root, lock.fileno())
            except Exception as exc:
                LOG.error('Worker cycle failed (%s); saved work will be retried.', type(exc).__name__)
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(args.interval)


if __name__ == '__main__':
    raise SystemExit(main())
