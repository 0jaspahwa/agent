# Corvo procurement decisions

[![CI](https://github.com/0jaspahwa/agent/actions/workflows/ci.yml/badge.svg)](https://github.com/0jaspahwa/agent/actions/workflows/ci.yml)

A buying agent for Corvo Engineering, a made-up company with two plants. People ask to buy things; the agent
decides how to buy each one (from a rate contract, with a direct order, or by asking suppliers for quotes), picks
the supplier and price, and says why, following the company's buying policy.

The policy is a data file, not code, so a policy change is uploaded, checked and approved in the app. Fixed rules
make every decision, so the same requests always get the same answers. AI only reads free text (a chat message, a
policy change, a contract PDF); it never decides.

**Hosted demo:** https://corvo-procurement-d2uh.onrender.com (Render, free plan). After 15 minutes without traffic it sleeps, and **the first
request after that can take up to a minute** while it starts again; later requests are fast.

| Read next | For |
|---|---|
| `DECISIONS.md` | Every point the policy leaves open and what we decided, grouped by theme, with the ten that matter most first |
| `APPROACH.md` | The AI tools used, where the LLM sits in the app and why it never decides, what was checked by hand |
| `docs/policy_schema.md` | The policy format, with one rule explained field by field |
| `docs/thursday.md` | The runbook for the blind test |
| `docs/manual_amendment_cheatsheet.md` | Entering a policy amendment by hand: the JSON for each kind of change and the sentence the app then shows (tested) |
| `docs/data_model.md`, `docs/deploy.md`, `docs/break_it.md` | The database; deploying to Render; the break-it pass |

## The task kit is not in this repo

The task rules say the public repo must not contain the task data files, so the kit (its CSVs, contract PDFs,
sample batch and PDFs of the brief, policy and worked examples) is not here; `data/` is gitignored. What the repo
does hold is ours: policy v5.0 written as JSON, the reviewed decision exports (golden files), the frontend's
recorded API responses, our stress batch and amendments, and the docs (DECISIONS.md D47). Provide the kit in either
of two ways:

1. **Put the kit's folders in `data/`**: unzip the kit and copy what is inside `Cantill_FullStack_Task_Kit/` so
   that `data/master_data/item_master.csv`, `data/contracts/contract_register.csv`, `data/contracts/pdf/*.pdf` and
   `data/pr_batches/sample_pr_batch.csv` exist. The app seeds from it on start (Docker mounts it read-only), and
   the tests that read the kit run.
2. **Upload the kit zip in the app**: sign in as Procurement → **Load kit data** → the zip exactly as distributed
   (or a zip without the top folder, or the CSV and contract PDF files) → **Load kit data**. Also on `/ops`, or
   `POST /api/admin/load-kit`. This is how the hosted app gets it (`docs/deploy.md`). Loading the same kit again
   changes nothing; a missing file is refused with its name; the sample batch is never loaded as data.

Until the kit is loaded, every screen shows "No kit data loaded. Procurement: load it under Load kit data.",
`/api/health` says `"kit_loaded": false`, and processing a batch is refused. Without `data/`, the tests that need
the kit skip with "kit data not present: put the kit in data/" (this is what CI runs).

## Run it locally

With Docker, one command (Postgres plus the app; tables created, and the kit seeded from `data/` on start):

```bash
docker compose up --build
```

Without Docker, with Python 3.13 and Node 22: install once,

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
```

then one command (a local SQLite database, the interface built on first run, no AI unless you add `--llm`):

```bash
.venv/Scripts/python scripts/dev_server.py
```

Open http://localhost:8000. The plain pages (no JavaScript, the fallback) are at `/ops`, the API docs at `/docs`.
On macOS or Linux the Python path is `.venv/bin/python`.

To process a batch from the command line, with no server or database:

```bash
.venv/Scripts/python scripts/run_batch.py data/pr_batches/sample_pr_batch.csv --out decisions.csv
```

## Roles

There is no login (DECISIONS.md D35): the first screen asks for a name and a role, the interface sends them with
every request, and the server checks the role on every action.

| Role | Screens | Can |
|---|---|---|
| Requester | New request (chat), My requests | Raise purchase requests by chat and follow them |
| Buyer | Workspace, Batches, Contracts, Preferred suppliers, Audit log | Approve or override decisions, process batches, add contracts |
| Procurement | Everything a Buyer has, plus Policy, Load kit data and the chat | Draft, approve and withdraw policy versions (also by describing a change in chat); load the task kit |

## API

| Method and path | What it does |
|---|---|
| `POST /api/admin/load-kit` | Load the task kit: the kit zip as distributed, a zip without its top folder, or the files (Procurement). Per table, the rows in the kit and the rows added |
| `POST /api/process-batch` | Process a PR batch CSV: multipart upload (any field name), raw CSV body, or JSON `{"csv": "..."}`. JSON response (run id, counts by route, one decision per line), or the export CSV with `?format=csv`. `policy_version=5.0` decides every requirement under that one approved version; otherwise each uses the version in force on its requirement date. Any role, or none |
| `GET /api/runs`, `GET /api/runs/{id}` | Runs, and one run's details (policy mode, hashes, counts) |
| `GET /api/runs/{id}/export.csv` | A run's decisions in the brief's format, byte for byte as when it ran |
| `GET /api/preferred-suppliers/export.csv?as_of=YYYY-MM-DD` | Top 3 preferred suppliers per item as of a date: `item_code, rank, supplier_id, reference_price` |
| `GET /api/preferred-suppliers?item_code=&as_of=` | One item's preferred list with every score's parts (Buyer, Procurement) |
| `GET /api/policies`, `GET /api/policies/{id}` | Policy versions and their status; one version with its plain-language changes and problems |
| `POST /api/policies/drafts` | A draft (Procurement): an amendment file or `{"text": ...}` drafted by the AI in the background (202, then poll the version), or `{"from_current": true}` with no AI (201) |
| `PUT /api/policies/drafts/{id}`, `POST .../preview?batch_id=`, `POST .../approve`, `POST .../discard` | Edit, preview the impact, approve, discard a draft (Procurement) |
| `POST /api/policies/{id}/withdraw` | Withdraw an approved version, with a comment (Procurement) |
| `GET /api/workspace?run_id=`, `GET /api/workspace/runs` | The buyer workspace: requirements with why, and NOT_PROCESSED lines (Buyer, Procurement) |
| `POST /api/requirements/{id}/approve`, `POST /api/requirements/{id}/override` | Buyer actions, with the requirement's version (409 if someone acted first) |
| `POST /api/chat/conversations`, `POST /api/chat/conversations/{id}/messages`, `GET /api/chat/requests` | Chat intake (Requester, Procurement) |
| `GET /api/contracts`, `POST /api/contracts/read-pdf`, `POST /api/contracts` | Contracts: list, read a PDF, add (Buyer, Procurement) |
| `GET /api/audit?actor=&action=` | The audit log, newest first (Buyer, Procurement) |
| `GET /api/suppliers`, `GET /api/items`, `GET /api/health` | Master data for forms; database status |

Who is asking travels in two headers: `X-User` (the name, percent-encoded) and `X-Role` (`Requester`, `Buyer` or
`Procurement`).

Process the sample batch and save the decisions (Run 1 under v5.0):

```bash
curl -s -F "file=@data/pr_batches/sample_pr_batch.csv" "http://localhost:8000/api/process-batch?format=csv&policy_version=5.0" -o run1.csv
```

Preferred suppliers as of 1 November 2026:

```bash
curl -s "http://localhost:8000/api/preferred-suppliers/export.csv?as_of=2026-11-01" -o preferred.csv
```

An amendment by hand, then Run 2 (the draft's id is in the first reply; here 2):

```bash
curl -s -H "X-User: Ojas" -H "X-Role: Procurement" -H "Content-Type: application/json" -d '{"from_current": true}' http://localhost:8000/api/policies/drafts
```
```bash
curl -s -X PUT -H "X-User: Ojas" -H "X-Role: Procurement" --data-binary @edited_policy.json http://localhost:8000/api/policies/drafts/2
```
```bash
curl -s -X POST -H "X-User: Ojas" -H "X-Role: Procurement" http://localhost:8000/api/policies/drafts/2/preview
```
```bash
curl -s -X POST -H "X-User: Ojas" -H "X-Role: Procurement" http://localhost:8000/api/policies/drafts/2/approve
```
```bash
curl -s -F "file=@data/pr_batches/sample_pr_batch.csv" "http://localhost:8000/api/process-batch?format=csv" -o run2.csv
```

Export columns, one row per PR line: `pr_no, pr_line, resolved_item_code, group_id, po_id, decision, route,
supplier_id, unit_price, group_value_inr, suggested_supplier_ids, policy_version, reason`.

## Tests

```bash
.venv/Scripts/python -m pytest -q
```
```bash
cd frontend && npm test
```

The backend tests run on SQLite with no setup (about 900, including 200 generated batches that take about five
minutes); with `TEST_DATABASE_URL` set to a Postgres database, the database tests run on Postgres too
(`docker compose -f docker-compose.test.yml up -d --wait` starts one on port 5433). They cover:
- all 14 worked examples on every printed field, and the three printed supplier rankings;
- the reviewed exports of the sample batch and the stress batch (`backend/tests/golden/`): any difference fails;
- a 46-line stress batch with expectations worked out from the data by hand (`backend/tests/fixtures/`);
- invariants over 200 generated batches; the break-it pass (`docs/break_it.md`);
- the policy evaluator, validator, change operations, amendment workflow (with a fake LLM) and nine rehearsal amendments;
- chat intake, the workspace (including two buyers at once), contracts, the API, and that no decision code imports the LLM.

CI (`.github/workflows/ci.yml`) runs on every push: the backend suite on SQLite and Postgres, the frontend tests and
build, and the Docker image started with `docker compose` and checked against both golden files through `curl`.

The frontend tests (Vitest) render every screen for every role from real API responses (`scripts/make_ui_fixtures.py`)
and test each screen's behaviour. One expected failure records that the worked examples' printed PO numbers are
ours minus one (D26).

## Known limitations

- **No login.** Name and role are self-declared and recorded; this prevents mistakes, not misuse (D35).
- **Approvals do not consume contract ceilings or add to PO history**, so runs stay repeatable; several approved
  chat orders could overdraw a contract (D14).
- **The ranking weights are fitted to the kit's 12 orderings.** Close calls the kit never tested could go either
  way (D24).
- **AI drafting depends on the Gemini key.** On the free tier it was slow and often unavailable; the manual path
  never needs it (D32, D38). Drafting by change operations has not yet been run against the real model (D33).
- **No migrations.** After a schema change the database is rebuilt once with `RESET_DB_ON_START=true` (`docs/deploy.md`).
- **Chat:** one plant, need-by date and urgency per request; the department is not asked (D41).
- **Contracts:** an uploaded PDF is read, not stored; only its file name is kept (D43).
- **The free hosting plan sleeps**; the first request after 15 idle minutes can take up to a minute.

## Layout

| Path | What it is |
|---|---|
| `backend/engine/` | The pure decision engine: validation, matching, clubbing, contracts, valuation, preferred suppliers, rules, consolidation, export |
| `backend/policies/` | Policy v5.0 as JSON |
| `backend/api/`, `backend/services/` | Thin HTTP handlers and the services they call |
| `backend/db/`, `backend/loaders/` | Database models and seed; loaders from the kit files and the database |
| `backend/llm/`, `backend/amendments/`, `backend/chat/` | The one LLM module and its prompts; amendment text and drafting; chat intake |
| `backend/tests/` | pytest |
| `frontend/` | The React interface (Vite, plain JavaScript, hand-written CSS); see `frontend/README.md` |
| `data/` | Where the task kit goes (not in the repo; see above) |
| `scripts/` | Command-line tools: run a batch, run the app locally, rehearse amendments, ranking evidence, fixtures |
| `docs/` | Schema, data model, test list, deploy steps, runbook, break-it pass, sample amendments, evidence |
