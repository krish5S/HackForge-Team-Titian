# Integration boundaries

- **Dev 1:** `backend/app/pipeline/`, `backend/app/llm/`, `backend/app/contracts/receipt.py`, model training/report assets, and processed month handoff.
- **Dev 2:** `backend/app/policy/`, `backend/app/evaluation/`, decision/policy contracts, and their unit tests.
- **Dev 3:** authentication, database persistence/migrations, API routers, `backend/app/services/` adapters, employee uploads, worker handoff/import, frontend, and application CI.

Integration changes should adapt contracts in the services layer rather than replacing teammate decision or extraction logic. Do not add GPU/training packages to the web server requirements. GitHub CODEOWNERS handles were not guessed; configure team handles when the repository administrators provide them.
