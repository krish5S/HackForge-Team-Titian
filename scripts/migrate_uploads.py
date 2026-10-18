"""Safely upgrade existing upload metadata without replacing application tables."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.db.database import Base, engine
from app.db import models  # register existing tables
from app.db.upload_migration import migrate_uploads

if __name__ == '__main__':
    Base.metadata.create_all(engine)
    migrate_uploads(engine)
    print('Upload metadata migration completed.')
