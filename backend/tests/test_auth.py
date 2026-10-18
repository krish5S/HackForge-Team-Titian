"""Authentication integration checks using a temporary SQLite database only."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, token_hash
from app.db.database import Base, get_db
from app.db.models import AuthSession, AuthUser, Employee
from app.main import app
from scripts.create_account import provision


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f'sqlite:///{Path(self.temp.name) / "test.db"}', connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.password = 'isolated-test-password-42'
        with Session(self.engine) as db:
            db.add(Employee(id='employee-test', name='Test Employee'))
            db.commit()
            provision(db, email='reviewer@example.test', display_name='Test Reviewer', role='REVIEWER', password=self.password)
            provision(db, email='employee@example.test', display_name='Test Employee', role='EMPLOYEE', employee_id='employee-test', password=self.password)
            db.commit()
        def isolated_db():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = isolated_db
        # Deliberately no context manager: do not run the real database lifespan.
        self.client = TestClient(app)
        self.origin = {'Origin': 'http://localhost:5173'}

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()
        self.temp.cleanup()

    def login(self, email='reviewer@example.test', **extra):
        return self.client.post('/api/auth/login', json={'email': email, 'password': self.password, **extra}, headers=self.origin)

    def test_public_health_and_protected_endpoints(self):
        self.assertEqual(self.client.get('/api/health').status_code, 200)
        for path in ['/api/auth/me', '/api/decisions', '/api/receipts/not-present', '/api/receipts/not-present/image']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()['error']['details'], {})

    def test_invalid_credentials_are_generic(self):
        missing = self.login('unknown@example.test')
        wrong = self.client.post('/api/auth/login', json={'email': 'reviewer@example.test', 'password': 'wrong'}, headers=self.origin)
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json(), wrong.json())
        self.assertNotIn('set-cookie', wrong.headers)

    def test_reviewer_session_refresh_rotation_and_logout(self):
        response = self.login(' REVIEWER@EXAMPLE.TEST ')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['role'], 'REVIEWER')
        self.assertEqual(set(response.json()), {'id', 'email', 'display_name', 'role', 'employee_id'})
        cookie = response.headers['set-cookie']
        for attribute in ['HttpOnly', 'SameSite=lax', 'Path=/', 'Max-Age=']:
            self.assertIn(attribute, cookie)
        token = self.client.cookies.get(COOKIE_NAME)
        with Session(self.engine) as db:
            stored = db.scalar(select(AuthSession))
            self.assertEqual(stored.token_hash, token_hash(token))
            self.assertNotEqual(stored.token_hash, token)
            self.assertTrue(db.scalar(select(AuthUser)).password_hash.startswith('$argon2id$'))
        # A new client with the cookie models session recovery after page refresh.
        refreshed = TestClient(app)
        refreshed.cookies.set(COOKIE_NAME, token)
        self.assertEqual(refreshed.get('/api/auth/me').status_code, 200)
        self.assertEqual(self.client.get('/api/decisions').json(), [])
        self.assertEqual(self.client.get('/api/receipts/not-present').status_code, 404)
        self.assertEqual(self.login().status_code, 200)
        new_token = self.client.cookies.get(COOKIE_NAME)
        self.assertNotEqual(token, new_token)
        self.assertEqual(refreshed.get('/api/auth/me').status_code, 401)
        response = self.client.post('/api/auth/logout', headers=self.origin)
        self.assertEqual(response.status_code, 204)
        self.assertIn('Max-Age=0', response.headers['set-cookie'])
        refreshed.cookies.set(COOKIE_NAME, new_token)
        self.assertEqual(refreshed.get('/api/auth/me').status_code, 401)
        refreshed.close()

    def test_employee_cannot_access_reviewer_data_or_choose_role(self):
        self.assertEqual(self.login('employee@example.test', role='REVIEWER').status_code, 422)
        response = self.login('employee@example.test')
        self.assertEqual(response.json()['role'], 'EMPLOYEE')
        self.assertEqual(response.json()['employee_id'], 'employee-test')
        for path in ['/api/decisions?role=REVIEWER', '/api/receipts/x', '/api/receipts/x/image']:
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_expired_and_forged_sessions(self):
        self.login()
        with Session(self.engine) as db:
            session = db.scalar(select(AuthSession))
            session.expires_at = int(time.time()) - 1
            db.commit()
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.client.get('/api/decisions').status_code, 401)
        self.client.cookies.clear()
        self.client.cookies.set(COOKIE_NAME, 'invented-token')
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)

    def test_origin_validation_and_credentialed_cors(self):
        for origin in [None, 'null', 'https://untrusted.example', 'http://localhost:5173.evil.test']:
            headers = {'Origin': origin} if origin else {}
            self.assertEqual(self.client.post('/api/auth/login', json={'email': 'reviewer@example.test', 'password': self.password}, headers=headers).status_code, 403)
            self.assertEqual(self.client.post('/api/auth/logout', headers=headers).status_code, 403)
        response = self.client.options('/api/auth/login', headers={**self.origin, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'})
        self.assertEqual(response.headers['access-control-allow-origin'], self.origin['Origin'])
        self.assertEqual(response.headers['access-control-allow-credentials'], 'true')

    def test_secure_cookie_configuration_and_clear_attributes(self):
        with patch('app.api.auth.COOKIE_SECURE', True):
            login = self.login()
            logout = self.client.post('/api/auth/logout', headers=self.origin)
            for response in [login, logout]:
                for attribute in ['Secure', 'HttpOnly', 'SameSite=lax', 'Path=/']:
                    self.assertIn(attribute, response.headers['set-cookie'])

    def test_provisioning_requires_explicit_identity_and_preserves_employees(self):
        base = dict(email='new@example.test', display_name='New Person', role='EMPLOYEE', password=self.password)
        with Session(self.engine) as db:
            for extra in [{}, {'employee_id': 'missing'}, {'employee_id': 'employee-test', 'create_employee': True, 'employee_name': 'Overwrite'}]:
                with self.assertRaises(ValueError):
                    provision(db, **base, **extra)
                db.rollback()
            with self.assertRaises(ValueError):
                provision(db, email=' REVIEWER@EXAMPLE.TEST ', display_name='Duplicate', role='REVIEWER', password=self.password)
            db.rollback()
            provision(db, **base, employee_id='explicit-new', create_employee=True, employee_name='Supplied Real Name', home_city='Supplied City')
            db.commit()
            self.assertEqual(db.get(Employee, 'employee-test').name, 'Test Employee')
            self.assertEqual(db.get(Employee, 'explicit-new').name, 'Supplied Real Name')


if __name__ == '__main__':
    unittest.main()
