"""Provision organization accounts; passwords never appear in process arguments."""
import argparse
from getpass import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.auth import normalize_email, password_hasher
from app.db.database import Base, SessionLocal, engine
from app.db.models import AuthUser, Employee


def provision(db, *, email, display_name, role, password, employee_id=None,
              create_employee=False, employee_name=None, home_city=None):
    email = normalize_email(email)
    if role not in ('EMPLOYEE', 'REVIEWER'):
        raise ValueError('Role must be EMPLOYEE or REVIEWER.')
    if not display_name.strip():
        raise ValueError('Display name is required.')
    if not 12 <= len(password) <= 1024:
        raise ValueError('Use a password between 12 and 1024 characters.')
    if db.scalar(select(AuthUser).where(AuthUser.email == email)):
        raise ValueError('An account already exists for that email.')
    if role == 'EMPLOYEE' and not employee_id:
        raise ValueError('EMPLOYEE accounts require an explicit --employee-id.')
    if create_employee:
        if not employee_id or not employee_name or not employee_name.strip():
            raise ValueError('--create-employee requires --employee-id and --employee-name.')
        if db.get(Employee, employee_id):
            raise ValueError('Employee ID already exists; omit --create-employee to link it.')
        db.add(Employee(id=employee_id, name=employee_name.strip(), home_city=home_city))
        db.flush()
    elif employee_name or home_city:
        raise ValueError('Employee identity fields require --create-employee.')
    elif employee_id and not db.get(Employee, employee_id):
        raise ValueError('Employee ID does not exist. Link an existing ID or explicitly create one.')
    user = AuthUser(email=email, display_name=display_name.strip(), role=role,
                    employee_id=employee_id, password_hash=password_hasher.hash(password))
    db.add(user)
    db.flush()
    return user


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email', required=True)
    parser.add_argument('--display-name', required=True)
    parser.add_argument('--role', required=True, choices=['EMPLOYEE', 'REVIEWER'])
    parser.add_argument('--employee-id')
    parser.add_argument('--create-employee', action='store_true')
    parser.add_argument('--employee-name')
    parser.add_argument('--home-city')
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error('Run in an interactive terminal for hidden password entry.')
    password = getpass('Password (12–1024 characters): ')
    if password != getpass('Confirm password: '):
        parser.error('Passwords do not match.')
    Base.metadata.create_all(bind=engine)
    try:
        with SessionLocal.begin() as db:
            user = provision(db, password=password, **vars(args))
            email, role = user.email, user.role
    except (ValueError, IntegrityError) as exc:
        parser.error(str(exc) if isinstance(exc, ValueError) else 'Account conflicts with an existing record.')
    print(f'Created {role} account for {email}.')


if __name__ == '__main__':
    main()
