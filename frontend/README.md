# The Receipt Graveyard frontend

Expense overview and read-only receipt evidence review in the existing Vite / React / TypeScript app.

## Run

```sh
cd frontend
npm install
npm run dev
```

Vite uses port 5173. Run the existing FastAPI backend separately on port 8001. `VITE_API_BASE_URL` configures the API root; its development fallback is `http://localhost:8001/api`. See `.env.example`; local `.env` files stay ignored.

```sh
npm run build
npm run lint
```

## Routes and behavior

- `/` redirects to `/queue`.
- `/queue` shows the queue. Verdict and employee filters are persisted in URL query parameters.
- `/receipts/:id` shows the same queue with receipt evidence selected.
- `/policy` and `/month-replay` are labelled placeholders.

The queue retains server ordering. Employee choices use a separate unfiltered query. TanStack Query keys include filters and receipt IDs, and fetches accept cancellation signals. Desktop details use an independently scrolling side panel; narrow screens use a stacked panel with keyboard focus, Escape/close controls, and focus restoration. Original previews use response MIME metadata and a native modal dialog for expansion.

Monetary strings are displayed without conversion or arithmetic. Decision currency is only shown if supplied by the decision; extraction currency does not determine decision currency. Missing currency is labelled. Missing values remain distinct from zero.

## Backend dependencies

Metrics and export are not implemented on the backend: metric values remain unavailable and CSV export is disabled. Evaluated receipts and original files must be loaded before populated queue / preview workflows can be exercised. Processed extraction/evidence payloads currently have only an unrestricted dictionary contract; optional sections render supplied field labels and values without inferring evidence.

## Verification limits

Production build and existing lint checks pass. The real database was inspected read-only, and actual health/decisions handlers returned zero receipts and an empty list. No sample receipts were inserted. The HTTP API was unreachable during implementation. Browser tooling was unavailable, so rendered desktop/mobile layouts, populated receipt selection, and file delivery still require browser verification with real data.

## Authentication

Routes now require a server session. `/login` uses the existing public artwork; reviewers enter `/queue` and employees enter `/employee`. See [authentication setup](../AUTHENTICATION.md) for exact account-provisioning commands, backend configuration, and isolated test instructions. The API client sends cookies and never stores tokens locally.
