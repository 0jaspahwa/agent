# APPROACH

How the app was built, which AI tools were used and for what, where an LLM sits inside the app and why it never
decides, and what was checked by hand.

## AI tools used, and for what

| Tool | Used for | Not used for |
|---|---|---|
| **Claude Code** (Claude Opus 5.5), in the Claude desktop app | Writing the code, tests, scripts and documents step by step, each step planned with Ojas and approved before the next (the log below). Reading the policy and example PDFs, investigating the data (`scripts/data_questions.py`, `scripts/ranking_constraints.py`, `scripts/stress_facts.py`), running the tests, and checking the interface in a browser | Deciding policy questions: every ambiguity was raised with Ojas and recorded in DECISIONS.md before it was built |
| **Gemini** (`gemini-3.6-flash`, Free Tier key) | Inside the app only: drafting a policy version from an amendment, reading a chat message, and reading a contract PDF the deterministic reader cannot read (next section). During the build: the spike's 9 amendment drafts and the 17 Nov rehearsal (results below) | Any decision. It is not on the decision path at all |

Ojas owns the code: the work went in small commits (one per step, with the reasoning in the commit message), and
every decision is written up with its evidence in DECISIONS.md.

## Where the LLM sits inside the app, and why it never decides

The rule: **the model describes, the code decides.** An LLM turns free text into structured
data; a deterministic engine makes every decision from data. Run 1 and Run 2 must be reproducible (the evaluators
may repeat them), scoring punishes "mostly right", and every decision must be explainable line by line.

| Where | What the LLM does | What code does with it | If the LLM is down |
|---|---|---|---|
| **Policy amendments** (Policy screen, `POST /api/policies/drafts`) | Proposes a new version as a short list of change operations, with what it could not express (D33) | Applies the operations to the approved version, validates every field against the fact catalogue, explains the change in plain words, previews its impact on a stored batch. Nothing takes effect until a Procurement user approves it (D34) | The draft fails visibly within 5 minutes at most; "edit the current version by hand" needs no AI (D38) |
| **Chat intake** (New request) | Extracts raw facts from a message: item words, quantity, unit, plant as written, date words, urgency, price, and whether the user confirms or corrects (D39) | Normalises them, matches the item deterministically, decides what to ask, writes every reply from templates; an item code is shown only if the matcher returned it | The pattern reader takes over, and the assistant says so once (D39) |
| **Contract PDFs** (Contracts screen), only when the buyer asks | Reads a contract's text into a form, marked "check every field" (D43) | The deterministic PDF reader always goes first; every field is validated, and the buyer confirms before saving | Fill the form by hand |

**Never on the decision path.** Processing or reprocessing a batch (Run 1, Run 2, the impact preview) reads only
the data and the stored, approved policy versions. No module on that path imports the LLM code:
`backend/tests/test_no_llm_in_decisions.py` checks the engine, the loaders and the batch-run service on their source.
The app is configured by `LLM_PROVIDER`, `LLM_MODELS` (ordered fallbacks) and the key `GEMINI`; failures are retried,
then the next model is tried, and every attempt is logged (D32).

**Real calls made.** The spike's 9 drafts (all answered by `gemini-3.6-flash`) plus the model listing; on 17 Nov, 11
requests (3 answered in 1.5 to 2.5 minutes each, 7 × 503, 1 × 429), after which real calls stopped until the paid
quota is live. Everything else is tested with a fake model.

## What was checked by hand

- **Every decision the policy leaves open** was raised with Ojas, who confirmed it (the status line of each entry in
  DECISIONS.md).
- **The worked examples** were checked field by field against the engine's output, and the expected values in the
  tests were taken from the example PDFs, never from the engine. Where they differed (the printed PO numbers, D26)
  the difference was investigated and recorded, not hidden.
- **The sample batch's export** was reviewed and frozen as a golden file; any change to it must be deliberate and
  explained in its commit.
- **The ranking weights** were fitted to the 12 orderings the kit prints, with the margins checked by
  `scripts/ranking_constraints.py` (D24).
- **The stress batch's expectations** (46 lines) and **the nine rehearsal amendments' expected changes** were worked
  out from the CSV files and the golden file by hand, before running the engine (D37, D46).
- **The interface** was clicked through in a browser (chat, workspace) and dry-run end to end with the Thursday
  runbook (docs/thursday.md).
- **The break-it pass** (docs/break_it.md) tried each attack against the running API and recorded what happened.
- **The README from scratch** (18 Nov): a fresh clone in a new folder, no Docker, following the README word for
  word: install, the one-command local run (it installed and built the interface itself), Run 1 through the README's
  curl and the command-line run (both identical to the golden file), 892 backend tests and 78 frontend tests passed.
  Nothing was missing from the README.
- **Secrets** (18 Nov): the whole history scanned. Only `.env.example` was ever committed; no key-shaped strings;
  the real key's value appears nowhere; the only password is the local development database's (`corvo`).

## AI usage log

Which AI tool was used, for what. The last column is for Ojas to tick as he reads each step's code.

| Date | Tool | Used for | Checked by Ojas |
|---|---|---|---|
| 2026-11-16 | Claude Code (Claude Opus 5.5) | Spike session, step 1: repo skeleton (folders, .gitignore, pinned requirements, FastAPI placeholder, smoke test), copied the kit into `data/`, first commit. Read the policy, worked examples and brief PDFs to prepare steps 2–4. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | Spike step 2: wrote `scripts/data_questions.py` to test valuation tie-breaks (Ex 11) and whether Blocked/Inactive POs count for valuation (Ex 5–12), plus the list of items whose latest PO is non-Active; drafted DECISIONS.md D1–D3. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | Boundary check: extended `scripts/data_questions.py` (crude free-text matcher, clubbing simulation under every reading, scans for lines/POs/requirements on each window boundary); drafted DECISIONS.md D4–D8; marked D1–D3 confirmed; updated the build notes. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | Spike step 3: policy schema (docs/policy_schema.md, with worked rule 5.3), v5.0 as JSON (backend/policies/v5.0.json), our own JSON Logic evaluator (backend/engine/logic.py) with tests, route test for Ex 1/5/8/10/11/12 plus limit-boundary cases; mutation-checked that the tests read the policy file; docs/engine_test_list.md; DECISIONS.md D4–D8 confirmed, D9–D10 added. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | Step 3 follow-ups: missing-value semantics in logic.py (comparisons false, missing fields reported; unknown fields caught by validation), fact catalogue (engine/facts.py), validator (engine/policy_check.py), rule walker with overrides (engine/policy.py), clubbing/consolidation keys, valuation order and supplier statuses as policy data; tests. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | Spike step 4: three sample amendments with machine-checkable expectations, scripts/try_amendment.py and its prompt (scripts/prompts/amendment_to_policy.md), provider set by LLM_PROVIDER (Gemini via REST), engine/policy_diff.py; float-noise rounding in logic.py (D11). First committed without running it against Gemini. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) + Gemini `gemini-3.6-flash` | Part A: listed the key's models and picked one, added the ranking tie-break (D13) and D12, let the checker pass inlined formulas with a note, ran the three amendments 3 times each, fixed a checker bug, updated the build notes. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | Spike close-out: committed the 9 raw Gemini drafts (docs/spike_results/, scanned for secrets), stage-based fact scopes in the validator (line check / override / rules) with tests, LLM resilience requirements and test list rows 36–45. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | Part B1: data model proposal (docs/data_model.md), awaiting approval; no model code written. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | B2: SQLAlchemy models for docs/data_model.md, append-only triggers, idempotent seed, Dockerfile and docker-compose (app + Postgres), a test Postgres compose file; DB tests on SQLite and Postgres. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | B3: engine input dataclasses (engine/inputs.py), PR CSV parser, kit loader, database loader, batch ingestion; equality test of both loaders on SQLite and Postgres. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | B4: deterministic contract PDF reader (pypdf, anchored on item codes and rates, refuses on any inconsistency); PDF-only contracts in the kit loader and seed; tests against the register. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | Answers to Part B (exact decimals in the evaluator, forgiving PR reader) and E1: line checks V3–V7 and flags F1–F6 as policy data, engine/validation.py, lines.py, versions.py, tests. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | E2: deterministic item matcher (engine/matching.py: number gate, word gate, Dice score, ambiguity), settings in v5.0.json, validator checks, tests (39 free-text lines, all coded lines with code hidden, all item descriptions, hard negatives). | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | E3: clubbing (engine/clubbing.py) driven by the clubbing parameters, overrides and per-requirement policy version; tests for worked examples 3, 5, 6, 14, boundaries, earliest-requirement rule, multi-line PRs, category override. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | E4: scripts/show_requirements.py; ticked the test list; file layout and D-table updated. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | Matching second pass (purpose clauses); engine F1–F6: contracts, valuation, preferred list with weights fitted to the kit's orderings (scripts/ranking_constraints.py), rules and outcomes, PO consolidation, decide() and the CSV export, scripts/run_batch.py; whole-engine tests. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | G1: POST /api/process-batch (api/upload.py, api/batches.py, services/runs.py, services/snapshot.py), stored runs, tests through the test client. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | G2: GET /api/runs, /api/runs/{id}, /api/runs/{id}/export.csv (regenerated from stored decisions), /api/preferred-suppliers/export.csv, /api/policies; engine/export.py preferred_csv; tests. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | G3: operations page at / (api/ops.py), plain HTML forms with no JavaScript; tests. | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | G4: API tests completed (time guard; coverage list). | |
| 2026-11-16 | Claude Code (Claude Opus 5.5) | G5: production Dockerfile, render.yaml, database URL normalisation, docs/deploy.md, README, secret scan of the full git history (clean: only .env.example ever committed, no key patterns, the real key absent; dev-only Postgres password in the compose files). | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | Postgres and Docker check: Docker Desktop failed to start (WSL bootstrap error 0xc00000fd), so the Postgres suite, image build and compose run could not be done; SQLite suite green. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | H1: one LLM module (backend/llm/client.py, gemini.py): ordered model list from LLM_MODELS, retry and fallback rules (D32), who answered recorded; tests with a fake provider. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | H2: amendment text from PDF, DOCX, text, Markdown or typed text (backend/amendments/extract.py, no LLM); simple_pdf.py test helper. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | H3: drafting (backend/amendments/drafting.py): full-document mode with not_expressed and translation_notes, incomplete without an effective date, manual draft from the current version; prompt moved to backend/llm/prompts. No real LLM call (D33). | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | H4: plain-language diff generated by code (engine/policy_explain.py); fixed policy_diff missing line_flags and other top-level keys. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | H5: impact preview of a draft on a batch (engine/impact.py), compared by line, with membership of requirements and POs and a reason when nothing changes. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | H6: policy version lifecycle (statuses, immutability trigger, services/amendments.py: draft, edit, preview, approve, discard, withdraw, audit); tests with a fake LLM (D34, D35). | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | H7: process a batch under one named version (D36); API, operations page, tests. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | H8: amendment endpoints (api/policies.py) and the /amendments pages without JavaScript (api/amendments_page.py); tests. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | H9: amendments A4–A9 (two as PDFs), scripts/rehearse_amendments.py with predictions from the golden file (D37), the manual rehearsal (9/9, docs/rehearsal/manual_run.md), test_rehearsal.py. Real-LLM rehearsal not run (waiting on the quota decision). | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) + Gemini `gemini-3.6-flash` | Part A1: real-LLM rehearsal through the app's draft endpoint (stopped at A5 on a free-tier 429; results recovered from the run's database into docs/rehearsal/llm_run_1.md); scored the three saved drafts offline; try_amendment.py taught to read `not_expressed`; gemini.py keeps Google's 429 reason and rejects cut-off replies; the rehearsal writes its report when it stops. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | Change operations (amendments/operations.py) and DRAFT_MODE, the condensed prompt (amendment_operations.md, 55k to 18k characters), background drafting with timeout and restart handling (D38), LLM_MODELS across providers, model and time on the amendments page, Render free plans and the cold-start note; tests with the fake LLM only. No real LLM calls. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | B1: React + Vite skeleton, identity screen, role-based navigation, FastAPI serving the build, ops pages moved to /ops, two-stage Dockerfile. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | B2: chat intake backend: pattern reader, LLM extraction prompt (raw facts only), conversation state machine, chat runs over open chat lines (D15), chat API; tests with a fake LLM and with the reader (D39-D41). No real LLM calls. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | B3: chat screen and My requests (React), dev server script without LLM; checked in the browser. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | B4: buyer workspace (service, API, React screen): approve, override, consolidated POs, conditional updates; fixtures from the real API for render tests; checked in the browser. | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | B5: batch screen. B6: contracts (service, API, screen): deterministic PDF reader first, AI reading only on request (fake LLM in tests), validation, the RC-2026-031 round trip back to the golden file (D43). | |
| 2026-11-17 | Claude Code (Claude Opus 5.5) | B7: policy screens (React) over the existing endpoints. B8, B9: preferred list and audit log (API and screens). Render smoke tests for every screen and role; README, D44. | |
| 2026-11-18 | Claude Code (Claude Opus 5.5) | RESET_DB_ON_START (drop, recreate, reseed once after a schema change) with docs/deploy.md 5a and tests. | |
| 2026-11-18 | Claude Code (Claude Opus 5.5) | S1: the stress batch (46 lines) with expectations worked out from the CSVs by scripts/stress_facts.py (no engine import), compared by test_stress.py: 46/46, 6 first mismatches all in the expectations. | |
| 2026-11-18 | Claude Code (Claude Opus 5.5) | S2: 200 generated batches checked for invariants (test_robustness.py), with a test that the checks catch tampering. Nothing found. | |
| 2026-11-18 | Claude Code (Claude Opus 5.5) | S3: break-it pass through the real API (docs/break_it.md): 9 findings fixed with tests, including a missing role check on policy drafts and a 4x speed-up of matching on large batches. | |
| 2026-11-18 | Claude Code (Claude Opus 5.5) | S4: Thursday runbook (docs/thursday.md), dry-run locally on the stress batch with amendment A-7; three checks in the runbook corrected. | |
| 2026-11-18 | Claude Code (Claude Opus 5.5) | S5: DECISIONS.md regrouped by theme with a top-ten summary, D45–D46, the ranking explained; this file; README; a fresh-clone run of the README; secret scan; tests for the history window edges and for no LLM import on the decision path. | |
| 2026-11-18 | Claude Code (Claude Opus 5.5) | Docker and Postgres check (Docker working again): full suite on Postgres, 1055 passed after fixing a test-only session leak that hung the Postgres teardown; image built and `docker compose up` checked (health, both golden files byte-identical through curl, the three printed rankings, / and /ops, restart, RESET_DB_ON_START); a second golden file for the stress batch; CI workflow. | |
| 2026-11-19 | Claude Code (Claude Opus 5.5) | The task kit taken out of the repo (task rules): Load kit data (endpoint, screen, /ops form) using the existing seed code; no-kit start with a banner and a health line; kit tests skip without data/; a SHA-256 check that no tracked file copies a kit file; runbook, deploy steps, README, D47. Verified: full suite with the kit, a copy without data/ loading the original zip, Docker with data/ mounted. | |

## Amendment translation results (spike, 2026-11-16)

`python scripts/try_amendment.py --all --runs 3`, model `gemini-3.6-flash`, temperature 0, JSON output mode, prompt `scripts/prompts/amendment_to_policy.md` with no prompt changes (round 0).

| Amendment | Runs valid | Runs correct | Notes |
|---|---|---|---|
| A1 limit and operator change | 3/3 | 3/3 | Spot 1,50,000 `<=`, emergency 7,50,000; nothing else changed |
| A2 CHK1 override + rule 5.3A | 3/3 | 3/3 | CHK1 spot limit as an override (`line.plant == CHK1`, value 1,00,000) every time; 5.3A placed between 5.3 and 5.4. The plant condition was `requirement.plant` in 2 runs and `plant.plant` in 1; both are catalogue fields |
| A3 price variance (new derived fact) | 3/3 | 3/3 after the checker fix (0/3 as first scored) | Every run added the derived fact `price_premium_pct` **and** a new limit `limits.price_variance {15, ">"}`, used through `meets_limit`, as prompt rule 3 asks. The first scoring flagged the new parameter as an "unexpected change": that was a **checker bug** (it did not allow new parameters), not a model error. All behaviour cases passed in every run. The checker now treats a new parameter as a note and still fails any change to an existing one; the same 9 saved drafts were rescored offline |

Model notes: on this Free Tier key, `gemini-3.1-pro-preview` has no quota (HTTP 429 on the first request), `gemini-2.5-pro`/`-flash` are "no longer available to new users" (HTTP 404), and `gemini-3.7-flash`/`3.8-flash` timed out or returned 503 under load. The first draft of the script had guessed `gemini-2.5-pro` as the default model, which would have failed; it now has no default and the model comes from `LLM_MODEL`.

## Real-LLM rehearsal (17 Nov)

`scripts/rehearse_amendments.py --llm`, whole-document mode, through the app's draft endpoint. The free tier
returned a 429 at the fifth amendment, and the run stopped as agreed (`docs/rehearsal/llm_run_1.md`). A1–A3 were
drafted correctly (valid, equivalent to the hand-made drafts, every behaviour case passing) but each took 1.5 to
2.5 minutes; A4 got only 503s. This is why drafting moved to change operations with a shorter prompt (D33) and runs
in the background (D38). The run in change-operations mode waits for the paid quota.
