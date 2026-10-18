PYTHON ?= .venv/bin/python

.PHONY: install migrate load evaluate backend frontend test build handoff
install:
	$(PYTHON) -m pip install -r backend/requirements/test.txt
	cd frontend && npm ci
migrate:
	$(PYTHON) scripts/migrate_uploads.py
load:
	$(PYTHON) scripts/load_database.py
evaluate:
	$(PYTHON) scripts/evaluate_database.py
backend:
	$(PYTHON) -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
frontend:
	npm --prefix frontend run dev -- --host localhost --port 5173
build:
	npm --prefix frontend run build
	npm --prefix frontend run lint
test:
	PYTHONPATH=backend:. $(PYTHON) -m unittest discover -s backend/tests -q
	$(PYTHON) -m pytest backend/tests/policy backend/tests/evaluation backend/tests/pipeline/test_reader_amounts.py backend/tests/pipeline/test_text_fallback.py -q
	$(MAKE) build
	cd frontend && node tests/session.mjs && node tests/submission.mjs
handoff:
	$(PYTHON) scripts/receipt_handoff.py export
