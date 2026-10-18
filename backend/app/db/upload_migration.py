"""Additive, repeatable SQLite migration for existing upload metadata."""
import hashlib
from pathlib import Path

from sqlalchemy import inspect, text

from app.db.database import PROJECT_ROOT


def migrate_uploads(engine, project_root: Path = PROJECT_ROOT):
    # BEGIN IMMEDIATE serializes concurrent startup/migration processes.
    with engine.connect() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        try:
            if 'submission_uploads' not in inspect(connection).get_table_names():
                connection.commit()
                return
            columns = {row['name'] for row in inspect(connection).get_columns('submission_uploads')}
            additions = {
                'user_id': 'VARCHAR REFERENCES auth_users(id)',
                'file_sha256': 'VARCHAR(64)',
                'processing_status': "VARCHAR NOT NULL DEFAULT 'UPLOADED'",
                'processing_error': 'TEXT',
            }
            for name, declaration in additions.items():
                if name not in columns:
                    connection.exec_driver_sql(f'ALTER TABLE submission_uploads ADD COLUMN {name} {declaration}')
            # Attribute legacy keys only when there is exactly one linked account.
            connection.execute(text("""UPDATE submission_uploads SET user_id =
                (SELECT min(id) FROM auth_users WHERE employee_id = submission_uploads.employee_id)
                WHERE user_id IS NULL AND (SELECT count(*) FROM auth_users
                  WHERE employee_id = submission_uploads.employee_id) = 1"""))
            rows = connection.execute(text('''SELECT u.submission_id, s.file_path
                FROM submission_uploads u JOIN submissions s ON s.id = u.submission_id
                WHERE u.file_sha256 IS NULL''')).all()
            root = (project_root / 'data/month/images').resolve()
            for submission_id, stored_path in rows:
                path = (project_root / stored_path).resolve()
                if not path.is_relative_to(root) or not path.is_file():
                    continue  # Never invent a hash for a missing original.
                try:
                    digest = hashlib.sha256()
                    with path.open('rb') as source:
                        for chunk in iter(lambda: source.read(65536), b''):
                            digest.update(chunk)
                except OSError:
                    continue
                connection.execute(text('UPDATE submission_uploads SET file_sha256=:digest WHERE submission_id=:id'),
                                   {'digest': digest.hexdigest(), 'id': submission_id})
            connection.commit()
        except Exception:
            connection.rollback()
            raise
