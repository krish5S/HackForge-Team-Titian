"""Handoff storage checked with an actual supplied image and processed payload.

This does not claim to run OCR or a GPU model on the demo laptop.
"""
import json
import unittest
from unittest.mock import patch
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db.database import PROJECT_ROOT
from app.db.models import ProcessingJob, Receipt, SubmissionUpload
from scripts.receipt_handoff import export_jobs, import_results
import test_employee


class HandoffTests(unittest.TestCase):
    setUpAuth = test_employee.EmployeeUploadTests.setUpAuth
    tearDownAuth = test_employee.EmployeeUploadTests.tearDownAuth
    setUp = test_employee.EmployeeUploadTests.setUp
    tearDown = test_employee.EmployeeUploadTests.tearDown
    login = test_employee.EmployeeUploadTests.login
    upload = test_employee.EmployeeUploadTests.upload

    def test_actual_file_export_import_retry_and_wrong_hash(self):
        original = (PROJECT_ROOT/'data/month/images/r_001.png').read_bytes()
        actual = json.loads((PROJECT_ROOT/'data/month/processed/r_001.json').read_text())
        submission = self.upload(content=original).json()
        bundle = self.root/'bundle'
        with patch('scripts.receipt_handoff.PROJECT_ROOT', self.root):
            with Session(self.engine) as db:
                self.assertEqual(export_jobs(db, bundle), 1)
                db.commit()
                self.assertEqual(export_jobs(db, bundle), 1)
                db.commit()
                job = db.scalar(select(ProcessingJob))
                job_id = job.id
                self.assertEqual(db.scalar(select(func.count()).select_from(ProcessingJob)), 1)
                self.assertEqual(db.scalar(select(SubmissionUpload)).processing_status, 'UPLOADED')
            manifest = json.loads((bundle/'jobs.json').read_text())
            self.assertEqual((bundle/manifest['jobs'][0]['image']).read_bytes(), original)
            actual['receipt_id'] = submission['id']
            result = {'job_id': job_id, 'submission_id': submission['id'], 'file_sha256': actual['file_sha256'], 'status': 'COMPLETED', 'receipt': actual}
            (bundle/'results.json').write_text(json.dumps({'results': [{**result, 'file_sha256': '0'*64}], 'duplicate_candidates': []}))
            with Session(self.engine) as db:
                with self.assertRaises(ValueError):
                    import_results(db, bundle)
                self.assertEqual(db.scalar(select(func.count()).select_from(Receipt)), 0)
            (bundle/'results.json').write_text(json.dumps({'results': [result], 'duplicate_candidates': []}))
            with Session(self.engine) as db:
                import_results(db, bundle)
                import_results(db, bundle)
                self.assertEqual(db.scalar(select(func.count()).select_from(Receipt)), 1)
                self.assertEqual(db.get(Receipt, submission['id']).submission_id, submission['id'])
                self.assertEqual(db.scalar(select(SubmissionUpload)).processing_status, 'PROCESSED')
                self.assertEqual(export_jobs(db, bundle), 0)

if __name__ == '__main__':
    unittest.main()
