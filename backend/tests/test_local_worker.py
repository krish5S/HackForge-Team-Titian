"""Coordinator recovery tests use isolated DBs and existing fixture results, not inference."""
import json
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import select, func
from sqlalchemy.orm import Session, sessionmaker
from app.db.database import PROJECT_ROOT
from app.db.models import ProcessingJob, Receipt, SubmissionUpload
from scripts.local_worker import cycle
from test_handoff import HandoffTests


class LocalWorkerTests(HandoffTests):
    def test_restart_after_import_retries_evaluation_without_inference(self):
        original = (PROJECT_ROOT/'data/month/images/r_001.png').read_bytes()
        actual = json.loads((PROJECT_ROOT/'data/month/processed/r_001.json').read_text())
        submission = self.upload(content=original).json()
        root = self.root/'local-worker'
        root.mkdir()
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            from pathlib import Path
            directory = Path(command[-1])
            job = json.loads((directory/'jobs.json').read_text())['jobs'][0]
            with Session(self.engine) as db:
                self.assertEqual(db.scalar(select(SubmissionUpload)).processing_status, 'PROCESSING')
            actual['receipt_id'] = submission['id']
            result = {**{k: job[k] for k in ('job_id', 'submission_id', 'file_sha256')},
                      'status': 'COMPLETED', 'receipt': actual}
            (directory/'results.json').write_text(json.dumps({'results': [result], 'duplicate_candidates': []}))
            return SimpleNamespace(returncode=0)

        with patch('scripts.receipt_handoff.PROJECT_ROOT', self.root), \
             patch('scripts.local_worker.SessionLocal', sessionmaker(self.engine)), \
             patch('scripts.local_worker.evaluate_processed', side_effect=[ValueError('evaluation failed'), SimpleNamespace(id='run')]):
            with self.assertRaises(ValueError):
                cycle(root, 1, runner=run)
            self.assertTrue((root/'active.json').exists())
            with Session(self.engine) as db:
                self.assertEqual(db.scalar(select(SubmissionUpload)).processing_status, 'PROCESSED')
            self.assertTrue(cycle(root, 1, runner=run))
            self.assertFalse(cycle(root, 1, runner=run))
            self.assertEqual(len(calls), 1)
            with Session(self.engine) as db:
                self.assertEqual(db.scalar(select(func.count()).select_from(Receipt)), 1)
                self.assertEqual(db.scalar(select(ProcessingJob)).status, 'COMPLETED')

    def test_worker_failure_is_persisted_not_retried_automatically(self):
        self.upload(content=(PROJECT_ROOT/'data/month/images/r_001.png').read_bytes())
        root = self.root/'local-worker'; root.mkdir()
        with patch('scripts.receipt_handoff.PROJECT_ROOT', self.root), \
             patch('scripts.local_worker.SessionLocal', sessionmaker(self.engine)), \
             patch('scripts.local_worker.evaluate_processed', return_value=None):
            self.assertTrue(cycle(root, 1, runner=lambda *a, **k: SimpleNamespace(returncode=1)))
            self.assertFalse(cycle(root, 1))
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(SubmissionUpload)).processing_status, 'FAILED')
            self.assertEqual(db.scalar(select(func.count()).select_from(Receipt)), 0)
