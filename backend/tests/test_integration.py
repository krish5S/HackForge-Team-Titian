"""Actual checked-in month, real evaluator and replay; isolated SQLite only."""
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from app.db.database import Base, get_db, PROJECT_ROOT
from app.db.models import (AuthUser, Employee, Policy, EvaluationRun, EvaluationArtifact,
                           Decision, Receipt, ReceiptAsset, Submission)
from app.main import app
from app.services.loader import load_month
from app.services.evaluations import save_evaluation, active_policy
from app.api.reviewer import period, EvaluateRequest
from app.evaluation import evaluate_month
from scripts.create_account import provision


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / 'database.db'
        cls.engine = create_engine(f'sqlite:///{cls.path}', connect_args={'check_same_thread': False})
        Base.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            load_month(db, PROJECT_ROOT/'data/month', PROJECT_ROOT/'data/policy')
            db.commit()
            assert load_month(db, PROJECT_ROOT/'data/month', PROJECT_ROOT/'data/policy')['submissions'] == 100
            start, end = period(db, EvaluateRequest())
            cls.run_id = save_evaluation(db, active_policy(db), start, end).id
            cls.period = (start, end)
            db.commit()
            provision(db, email='integration-reviewer@example.test', display_name='Test reviewer', role='REVIEWER', password='temporary-test-password')
            provision(db, email='integration-employee@example.test', display_name='Test employee', role='EMPLOYEE', employee_id='e_01', password='temporary-test-password')
            db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.temp.cleanup()

    def setUp(self):
        def isolated_db():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = isolated_db
        self.client = TestClient(app)
        self.headers = {'Origin': 'http://localhost:5173'}
        self.login('integration-reviewer@example.test')

    def login(self, email):
        response = self.client.post('/api/auth/login', json={'email': email, 'password': 'temporary-test-password'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()

    def test_actual_queue_metrics_export_and_files(self):
        rows = self.client.get('/api/decisions').json()
        metrics = self.client.get('/api/metrics').json()
        self.assertEqual(len(rows), 100)
        self.assertEqual(metrics['evaluated'], 100)
        self.assertEqual(metrics['run_id'], self.run_id)
        self.assertTrue(all(row['currency'] == metrics['currency'] for row in rows))
        exported = list(csv.DictReader(io.StringIO(self.client.get('/api/exports/decisions').text)))
        self.assertEqual(len(exported), len(rows))
        self.assertEqual({r['receipt_id'] for r in exported}, {r['receipt_id'] for r in rows})
        for rid, mime in [('r_001','image/png'), ('r_018','application/pdf')]:
            response = self.client.get(f'/api/receipts/{rid}/image')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['content-type'], mime)
            detail = self.client.get(f'/api/receipts/{rid}').json()
            self.assertEqual(detail['evaluation_run_id'], self.run_id)
            self.assertTrue(detail['decision']['currency'])
        approved = self.client.get('/api/decisions?verdict=APPROVE').json()
        self.assertTrue(all(row['verdict'] == 'APPROVE' for row in approved))

    def test_real_timeline_snapshot_and_budget(self):
        timeline = self.client.get('/api/timeline').json()
        self.assertEqual(len(timeline['events']), 100)
        event = timeline['events'][35]
        response = self.client.get('/api/replay', params={'as_of': event['submitted_at'], 'run_id': self.run_id})
        self.assertEqual(response.status_code, 200)
        with Session(self.engine) as db:
            frozen = db.get(EvaluationArtifact, self.run_id).input_json
            expected = evaluate_month(frozen, as_of=event['submitted_at']).model_dump(mode='json')
        self.assertEqual(response.json()['snapshot'], expected)
        self.assertEqual(self.client.get('/api/replay?as_of=2026-09-01T00:00:00').status_code, 422)
        self.assertLess(len(expected['decisions']), 100)
        self.assertEqual(self.client.get('/api/replay', params={'as_of': event['submitted_at'], 'run_id': 'missing'}).status_code, 404)

    def test_evaluation_idempotency_and_failure_keep_previous_run(self):
        response = self.client.post('/api/evaluations', headers=self.headers, json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['run_id'], self.run_id)
        with patch('app.services.evaluations.build_input', side_effect=ValueError('Invalid processing input')):
            failed = self.client.post('/api/evaluations', headers=self.headers, json={})
        self.assertEqual(failed.status_code, 422)
        self.assertEqual(self.client.get('/api/metrics').json()['run_id'], self.run_id)

    def test_policy_unavailable_preserves_active_and_authorization(self):
        policy = self.client.get('/api/policies/active').json()
        with patch('app.policy.compiler._extractor', None):
            result = self.client.post(f"/api/policies/{policy['id']}/compile", json={}, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(result.json()['activated'])
        self.assertEqual(self.client.get('/api/policies/active').json()['id'], policy['id'])
        self.login('integration-employee@example.test')
        for path in ['/api/policies/active','/api/metrics','/api/timeline','/api/replay?as_of=2026-09-10T00:00:00Z','/api/exports/decisions']:
            self.assertEqual(self.client.get(path).status_code, 403)
        own = self.client.get('/api/employee/submissions').json()
        self.assertTrue(own)
        self.assertTrue(all(row['decision'] is not None for row in own))
        self.assertEqual(self.client.get('/api/employee/submissions/r_003').status_code, 404)
        self.assertEqual(self.client.get('/api/employee/submissions/r_001/file').status_code, 200)

    def test_import_identity_conflict_rolls_back(self):
        with Session(self.engine) as db:
            employee = db.get(Employee, 'e_01')
            old = employee.name
            employee.name = 'Different identity'
            db.flush()
            with self.assertRaisesRegex(ValueError, 'identity conflict'):
                load_month(db, PROJECT_ROOT/'data/month', PROJECT_ROOT/'data/policy')
            db.rollback()
            self.assertEqual(db.get(Employee, 'e_01').name, old)

    def test_csv_formula_escaping_and_empty_export(self):
        from app.api.reviewer import csv_cell, export
        self.assertTrue(csv_cell('  =HYPERLINK("bad")').startswith("'"))
        self.assertEqual(csv_cell('12.00'), '12.00')
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            self.assertEqual(len(list(csv.reader(io.StringIO(export(db).body.decode())))), 1)
        engine.dispose()


if __name__ == '__main__':
    unittest.main()
