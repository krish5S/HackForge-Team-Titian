import io
import hashlib
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import select, func, create_engine, text
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

import test_auth
from app.main import app
from app.db.models import Submission, Receipt, SubmissionUpload, Employee, Policy, EvaluationRun, Decision
from scripts.create_account import provision


class EmployeeUploadTests(unittest.TestCase):
    setUpAuth = test_auth.AuthTests.setUp
    tearDownAuth = test_auth.AuthTests.tearDown
    login = test_auth.AuthTests.login

    def setUp(self):
        self.setUpAuth()
        self.root = Path(self.temp.name)
        self.files = self.root / 'data' / 'month' / 'images' / 'uploads'
        self.patches = [patch('app.api.employee.PROJECT_ROOT', self.root), patch('app.api.employee.UPLOAD_ROOT', self.files)]
        for item in self.patches:
            item.start()
        with Session(self.engine) as db:
            db.add(Employee(id='other-employee', name='Other Employee'))
            db.commit()
            provision(db, email='other@example.test', display_name='Other Employee', role='EMPLOYEE', employee_id='other-employee', password=self.password)
            db.commit()
        self.login('employee@example.test')
        output = io.BytesIO()
        Image.new('RGB', (20, 20), 'white').save(output, format='PNG')
        self.content = output.getvalue()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tearDownAuth()

    def upload(self, key='test-key-1234567890', content=None, filename='receipt.png', data=None, client=None):
        return (client or self.client).post('/api/employee/submissions',
            headers={**self.origin, 'Idempotency-Key': key},
            data=data if data is not None else {'purpose': 'Client meeting', 'attendee_count': '0'},
            files={'file': (filename, self.content if content is None else content, 'application/octet-stream')})

    def test_saved_original_context_and_pending_state(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        row = response.json()
        self.assertEqual(row['status'], 'UPLOADED')
        self.assertIsNone(row['decision'])
        self.assertEqual(row['fields']['attendee_count'], 0)
        self.assertEqual(self.client.get(f"/api/employee/submissions/{row['id']}/file").content, self.content)
        self.assertEqual(self.client.get('/api/employee/submissions').json()[0]['id'], row['id'])
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Receipt)), 0)
            self.assertEqual(db.get(Submission, row['id']).employee_id, 'employee-test')

    def test_idempotent_retry_changed_body_and_deliberate_new_upload(self):
        first = self.upload().json()
        self.assertEqual(self.upload().json()['id'], first['id'])
        self.assertEqual(self.upload(data={'purpose': 'Different purpose'}).status_code, 409)
        second = self.upload(key='deliberate-new-key-123').json()
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(len(list(self.files.iterdir())), 2)

    def test_concurrent_retries_create_one_record_and_file(self):
        cookies = dict(self.client.cookies)
        # Avoid lifespan: real application DB must never be opened by these tests.
        def concurrent_upload(_):
            client = TestClient(app)
            client.cookies.update(cookies)
            try:
                response = self.upload(client=client)
                return response.status_code, response.json()
            finally:
                client.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(concurrent_upload, range(2)))
        self.assertEqual([result[0] for result in results], [201, 201], results)
        self.assertEqual(results[0][1]['id'], results[1][1]['id'])
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SubmissionUpload)), 1)
        self.assertEqual(len(list(self.files.iterdir())), 1)

    def test_ownership_non_disclosure_and_identity_injection(self):
        row = self.upload().json()
        self.login('other@example.test')
        self.assertEqual(self.client.get('/api/employee/submissions').json(), [])
        for ending in ['', '/file']:
            foreign = self.client.get(f"/api/employee/submissions/{row['id']}{ending}")
            absent = self.client.get(f'/api/employee/submissions/unknown{ending}')
            self.assertEqual(foreign.status_code, 404)
            self.assertEqual(foreign.json(), absent.json())
        self.assertEqual(self.upload(data={'purpose': 'Expense', 'employee_id': 'employee-test'}).status_code, 422)
        self.login()
        self.assertEqual(self.client.get('/api/employee/submissions').status_code, 403)
        self.assertEqual(self.upload().status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.upload().status_code, 401)

    def test_validation_and_supported_types(self):
        for filename, content, expected in [('bad.png', b'not an image', 422), ('bad.svg', b'<svg/>', 415), ('empty.png', b'', 413), ('large.png', b'x' * (10 * 1024 * 1024 + 1), 413)]:
            self.assertEqual(self.upload(filename=filename, content=content).status_code, expected)
        self.assertEqual(self.upload(data={'purpose': '   '}).status_code, 422)
        self.assertEqual(self.upload(data={'purpose': 'Expense', 'attendee_count': '-1'}).status_code, 422)
        for index, (format, suffix) in enumerate([('JPEG', '.jpg'), ('WEBP', '.webp')]):
            output = io.BytesIO()
            Image.new('RGB', (10, 10)).save(output, format=format)
            self.assertEqual(self.upload(key=f'format-test-key-{index:04}', content=output.getvalue(), filename='receipt' + suffix).status_code, 201)
        pdf = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(pdf)
        response = self.upload(key='pdf-format-key-12345', filename='receipt.pdf', content=pdf.getvalue())
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(self.client.get(f"/api/employee/submissions/{response.json()['id']}/file").headers['content-type'], 'application/pdf')

    def test_stream_size_limit_and_csrf(self):
        response = self.client.post('/api/employee/submissions', content=iter([b'x' * 1024 * 1024] * 12), headers={**self.origin, 'Idempotency-Key': 'stream-test-key-123', 'Content-Type': 'multipart/form-data; boundary=x'})
        self.assertEqual(response.status_code, 413)
        response = self.client.post('/api/employee/submissions', files={'file': ('receipt.png', self.content)}, data={'purpose': 'Expense'}, headers={'Idempotency-Key': 'origin-test-key-123'})
        self.assertEqual(response.status_code, 403)

    def test_storage_failure_and_missing_file(self):
        with patch('app.api.employee.os.fsync', side_effect=OSError('disk failure')):
            self.assertEqual(self.upload().status_code, 503)
        self.assertEqual(self.client.get('/api/employee/submissions').json(), [])
        self.assertEqual(list(self.files.iterdir()), [])
        row = self.upload().json()
        for file in self.files.iterdir():
            file.unlink()
        self.assertEqual(self.client.get(f"/api/employee/submissions/{row['id']}/file").status_code, 404)
        self.assertEqual(self.client.get(f"/api/employee/submissions/{row['id']}").status_code, 200)

    def test_only_real_processed_and_evaluated_results(self):
        row = self.upload().json()
        with Session(self.engine) as db:
            db.add(Receipt(id='real-processed', submission_id=row['id'], processed_json={'extraction_status': 'PARTIAL', 'ocr_text': 'Visible receipt text', 'extraction': {'total': '10.00', 'readers': {'reader_b_error': {'message': 'failure'}}}}))
            db.add(Policy(id='policy', source_text='Test policy'))
            db.commit()
        detail_url = f"/api/employee/submissions/{row['id']}"
        detail = self.client.get(detail_url).json()
        self.assertEqual(detail['status'], 'PROCESSED')
        self.assertEqual(detail['ocr_text'], 'Visible receipt text')
        self.assertEqual(detail['extraction']['total'], '10.00')
        self.assertNotIn('readers', detail['extraction'])
        self.assertTrue(detail['processing_warnings'])
        self.assertNotIn('ocr_text', self.client.get('/api/employee/submissions').json()[0])
        with Session(self.engine) as db:
            db.add(EvaluationRun(id='run', policy_id='policy', policy_version=1, period='test', status='COMPLETED'))
            db.commit()
            db.add(Decision(run_id='run', receipt_id='real-processed', verdict='APPROVE', amounts_json={'reimbursable': '0.00'}, reasons_json=[{'message': 'Actual test evaluation'}]))
            db.commit()
        result = self.client.get(detail_url).json()
        self.assertEqual(result['status'], 'EVALUATED')
        self.assertEqual(result['decision']['amounts']['reimbursable'], '0.00')

    def test_retry_scope_is_account_not_employee_record(self):
        first = self.upload().json()
        with Session(self.engine) as db:
            provision(db, email='second-login@example.test', display_name='Second login', role='EMPLOYEE',
                      employee_id='employee-test', password=self.password)
            db.commit()
        self.login('second-login@example.test')
        second = self.upload().json()
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(self.upload().json()['id'], second['id'])

    def test_legacy_retry_is_preserved_or_conflicts_when_ambiguous(self):
        first = self.upload().json()
        with Session(self.engine) as db:
            upload = db.scalar(select(SubmissionUpload))
            upload.idempotency_key = 'test-key-1234567890'
            db.commit()
        self.assertEqual(self.upload().json()['id'], first['id'])
        with Session(self.engine) as db:
            upload = db.scalar(select(SubmissionUpload))
            upload.user_id = None
            db.commit()
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(len(self.client.get('/api/employee/submissions').json()), 1)

    def test_file_hash_restart_and_explicit_failure_state(self):
        row = self.upload().json()
        with Session(self.engine) as db:
            upload = db.scalar(select(SubmissionUpload))
            self.assertEqual(upload.file_sha256, hashlib.sha256(self.content).hexdigest())
            self.assertEqual(upload.processing_status, 'UPLOADED')
        self.engine.dispose()
        self.engine = create_engine(f'sqlite:///{self.root / "test.db"}', connect_args={'check_same_thread': False})
        self.assertEqual(self.upload().json()['id'], row['id'])
        self.assertEqual(self.client.get(f"/api/employee/submissions/{row['id']}/file").content, self.content)
        with Session(self.engine) as db:
            upload = db.scalar(select(SubmissionUpload))
            upload.processing_status = 'FAILED'
            upload.processing_error = 'The document could not be read. Contact the expense team.'
            db.commit()
        result = self.client.get(f"/api/employee/submissions/{row['id']}").json()
        self.assertEqual(result['processing_status'], 'FAILED')
        self.assertIn('could not be read', result['processing_error'])
        self.assertIsNone(result['decision'])

    def test_latest_global_run_matches_reviewer_queue(self):
        self.test_only_real_processed_and_evaluated_results()
        with Session(self.engine) as db:
            db.add(EvaluationRun(id='newer', policy_id='policy', policy_version=1, period='test',
                                status='COMPLETED', created_at='2999-01-01T00:00:00Z'))
            db.commit()
        result = self.client.get('/api/employee/submissions').json()[0]
        self.assertIsNone(result['decision'], 'Do not fall back to an obsolete decision absent from the newest completed run')
        self.assertEqual(result['processing_status'], 'PROCESSED')

    def test_repeatable_legacy_migration(self):
        from app.db.upload_migration import migrate_uploads
        legacy = create_engine(f'sqlite:///{self.root / "legacy.db"}')
        self.files.mkdir(parents=True)
        original = self.files / 'legacy.png'
        original.write_bytes(self.content)
        with legacy.begin() as db:
            db.exec_driver_sql('CREATE TABLE auth_users (id TEXT PRIMARY KEY, employee_id TEXT)')
            db.exec_driver_sql('CREATE TABLE submissions (id TEXT PRIMARY KEY, file_path TEXT)')
            db.exec_driver_sql('CREATE TABLE submission_uploads (employee_id TEXT, idempotency_key TEXT, submission_id TEXT, request_hash TEXT, original_name TEXT, media_type TEXT, size_bytes INTEGER, PRIMARY KEY(employee_id,idempotency_key))')
            db.exec_driver_sql("INSERT INTO auth_users VALUES ('u','e')")
            db.execute(text('INSERT INTO submissions VALUES (:id,:path)'), {'id': 's', 'path': str(original.relative_to(self.root))})
            db.exec_driver_sql("INSERT INTO submission_uploads VALUES ('e','old-key','s','original-request-hash','original.png','image/png',1)")
        migrate_uploads(legacy, self.root)
        migrate_uploads(legacy, self.root)
        with legacy.connect() as db:
            row = db.execute(text('SELECT * FROM submission_uploads')).mappings().one()
            self.assertEqual(row['user_id'], 'u')
            self.assertEqual(row['request_hash'], 'original-request-hash')
            self.assertEqual(row['file_sha256'], hashlib.sha256(self.content).hexdigest())
            self.assertEqual(row['processing_status'], 'UPLOADED')
        self.assertEqual(original.read_bytes(), self.content)
        legacy.dispose()


if __name__ == '__main__':
    unittest.main()
