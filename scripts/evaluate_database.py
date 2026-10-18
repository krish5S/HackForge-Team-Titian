"""Evaluate real processed database receipts with the active saved policy."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.db.database import SessionLocal
from app.api.reviewer import evaluate, EvaluateRequest
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start')
    parser.add_argument('--end')
    args = parser.parse_args()
    with SessionLocal() as db:
        print(evaluate(EvaluateRequest(start=args.start, end=args.end), db))
