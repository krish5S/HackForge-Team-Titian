"""Import Dev 1's supplied month transactionally, without touching auth accounts."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.db.database import Base, engine, SessionLocal, PROJECT_ROOT
from app.db.upload_migration import migrate_uploads
from app.services.loader import load_month

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--month', type=Path, default=PROJECT_ROOT / 'data/month')
    parser.add_argument('--policy', type=Path, default=PROJECT_ROOT / 'data/policy')
    args = parser.parse_args()
    Base.metadata.create_all(engine)
    migrate_uploads(engine)
    try:
        with SessionLocal.begin() as db:
            print(load_month(db, args.month, args.policy))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Import rolled back: {exc}\n')
