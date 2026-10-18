# Authentication setup

Run commands below from the repository root unless noted. Accounts are organization-provisioned; there is no public registration and no seeded credentials.

## Install and run

```sh
.venv/bin/python -m pip install -r backend/requirements/api.txt
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
```

In a second terminal:

```sh
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The frontend uses `VITE_API_BASE_URL=http://localhost:8001/api` (the existing fallback). Use the same hostname for frontend and backend: when opening `http://127.0.0.1:5173`, set the API URL to `http://127.0.0.1:8001/api` and restart Vite. Mixing localhost and 127.0.0.1 prevents SameSite cookies from working.

## Create real accounts

Replace the quoted placeholders with supplied organization details. Each command prompts twice for a hidden password (12–1024 characters). Passwords are not accepted as command-line arguments. The command adds tables if needed; existing employees and receipts are never overwritten.

Reviewer, without an employee link:

```sh
.venv/bin/python scripts/create_account.py --role REVIEWER --email '<reviewer-email>' --display-name '<reviewer-name>'
```

Employee, linked to an explicitly identified existing Employee row:

```sh
.venv/bin/python scripts/create_account.py --role EMPLOYEE --email '<employee-email>' --display-name '<employee-name>' --employee-id '<existing-employee-id>'
```

Explicitly provision a new employee record and its account together:

```sh
.venv/bin/python scripts/create_account.py --role EMPLOYEE --email '<employee-email>' --display-name '<employee-name>' --employee-id '<new-employee-id>' --create-employee --employee-name '<real-employee-name>' --home-city '<real-home-city>'
```

Omit `--home-city` if it is not supplied. Reviewers can also be linked using `--employee-id`. The script rejects duplicate normalized emails, missing employee links, invalid roles, and attempts to overwrite existing employee records. A failed transaction rolls back the account and any newly provisioned employee together.

## Configuration

Backend defaults are documented in `backend/.env.example`:

- `AUTH_COOKIE_SECURE=false` for local HTTP; set `true` for HTTPS deployments.
- `AUTH_SESSION_SECONDS=28800` gives an eight-hour session.
- `AUTH_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173` lists exact trusted frontend origins. Configure your actual HTTPS origin when deploying.

To use a local backend `.env`, create it from the example without overwriting existing settings, then run:

```sh
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001 --env-file backend/.env
```

Local `.env` files and SQLite data remain Git-ignored. There is no static session signing secret: sessions use random opaque tokens, with only SHA-256 hashes stored in SQLite. Cookies are HttpOnly, SameSite=Lax, Path=/, and use the configured Secure attribute on both creation and deletion. Passwords use the maintained [argon2-cffi PasswordHasher](https://argon2-cffi.readthedocs.io/en/stable/howto.html). Password rehashing occurs on login when parameters change.

## API and authorization

- `POST /api/auth/login`: JSON email and password only; returns safe user fields and sets a new session cookie. Generic 401 for invalid credentials.
- `GET /api/auth/me`: restores the session from the cookie; 401 for missing, forged, or expired sessions.
- `POST /api/auth/logout`: invalidates the current token and clears the cookie, including when already expired.

Login and logout require an exact allowed `Origin` header, including non-browser clients. Credentialed CORS uses explicit origins. Decisions and both receipt endpoints require the server's REVIEWER role; health remains public. `current_user` and `require_reviewer` are reusable dependencies for future API routes. Future mutation endpoints must also use `validate_origin`.

The UI stores no session tokens. It waits for `/auth/me` before rendering protected content, redirects employees to `/employee` and reviewers to `/queue`, and clears private queries on logout, expiry, or identity changes. Session checks also run on focus and every minute. A failed logout remains visible with a retryable action, rather than claiming the server session was invalidated.

## Verification

```sh
.venv/bin/python -m pip install -r backend/requirements/test.txt
PYTHONPATH=backend:. .venv/bin/python -m unittest discover -s backend/tests -v
npm --prefix frontend run build
npm --prefix frontend run lint
cd frontend
node tests/session.mjs
```

Backend checks use temporary SQLite databases and dependency overrides without starting the production database lifespan. They cover invalid login, reviewer and employee roles, cookie recovery, rotation, logout invalidation, expiration, forged tokens, origin/CORS enforcement, secure-cookie attributes, and safe employee provisioning. The real database checksum was unchanged before and after tests.

Frontend checks cover role destinations, private-cache clearing after account changes and expired sessions, and byte-identical inclusion of the existing artwork in the build. No new real accounts were provisioned. Browser tooling and the separate layout-reference screenshot were unavailable: desktop/mobile visual checks, interactive login/logout navigation, and real populated receipt workflows remain unverified. The existing finance-team artwork was visually inspected and is displayed without cropping at `/login-image.png`.

### Login-flow audit

The account provisioner and API import the same engine and auth models. The running API's open SQLite file was verified as the shared absolute `data/receipt_graveyard.db` path, with one existing REVIEWER account and one EMPLOYEE account; no hashes or tokens were printed. Live localhost CORS preflight passed with credentials enabled.

The original removed-session-query observer defect has already been corrected. Login now additionally cancels old session checks, posts only email/password, verifies the cookie with `/auth/me`, updates the mounted session query, and explicitly navigates using the confirmed server role. A rejected cookie now produces a visible diagnostic rather than treating the POST response alone as a usable session. Tests cover an old unauthenticated response arriving after login, blocked cookies, incorrect credentials, and network failure. The remaining real-account browser failure could not be reproduced without a browser session or credentials; no real-account success is claimed.
