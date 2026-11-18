# Data model

**Status: approved by Ojas, 2026-11-16, with the answers in the last section folded in.** Postgres, through SQLAlchemy. Tables are created on startup, with no migrations tool, and seeded from `data/` (safe to run twice).

## Principles

1. **The engine never touches the database.** A loader turns the tables into plain dataclasses (`backend/engine/inputs.py`). `decide(...)` returns plain results, and the app writes them back. A second loader builds the same dataclasses from the kit CSVs, and a test proves both give identical objects.
2. **Engine inputs are never changed by using the app.** Runs, approvals and overrides never write to master data, PO history or contract consumed values. The only additions are new contracts (contracts screen) and new policy versions, and both are audited. This is what makes Run 1 and Run 2 repeatable.
3. **A run is an immutable snapshot.** It stores the batch it processed, the ceiling baseline it used, every policy version it applied, and its full output.
4. **Nothing is overwritten.** A buyer's approval or override is a new row in `buyer_actions`, beside the run's original decision. `audit_log` and `buyer_actions` are **append-only**: a database trigger rejects `UPDATE` and `DELETE` on both.
5. **Identity without authentication.** The UI asks once for a display name and a role (Requester, Buyer or Procurement), and sends them as `X-User` and `X-Role` on every request. The API refuses a write without `X-User`. Who-columns store the name as text. There is no users table; the role shapes the UI only.

**Types**
- **Money, rates and prices:** `numeric(16,2)`. **Quantities:** `numeric(14,3)`. **Ratings:** `numeric(5,2)`. All exact decimals: Python `Decimal`, never `float`, in the database and in the loaders.
- **PR `created_at`:** `timestamp` **without** time zone, stored exactly as given in the CSV (minute precision, IST wall-clock, no conversion). The 14-day and 24-hour windows are computed on these values as they are.
- **Dates:** `date`. **App timestamps** (`*_at` written by the app): `timestamptz`.
- **JSON:** `jsonb` on Postgres. **Lists** (categories, suggested suppliers, version ids) are JSON arrays.

## Master data (engine input)

**items**: the item master; matching, item type (Capex) and the standard price come from here.

| Column | Type | Key |
|---|---|---|
| item_code | text | PK |
| description, uom, category, item_type | text | |
| standard_price | numeric | |

**suppliers**: status (5.7), categories (6.4 top-up) and the ratings used by the ranking.

| Column | Type | Key |
|---|---|---|
| supplier_id | text | PK |
| name, city | text | |
| categories | json list | the kit's `;`-separated list, split |
| status | text | check in (Active, Blocked, Inactive) |
| on_time_pct, quality_rating | numeric | |

**plants**: valid plant codes. An unknown plant on a line is `NOT_PROCESSED` (V2).

| Column | Type | Key |
|---|---|---|
| plant | text | PK |
| name | text | |

**po_history**: the kit's past POs, for valuation (3.1b), "bought from an Active supplier" (5.3/5.4) and the preferred list (6.1–6.3). Approved POs from the app are **never** added here (D14).

| Column | Type | Key |
|---|---|---|
| po_number | text | PK |
| po_date | date | index (item_code, po_date) |
| supplier_id | text | FK suppliers |
| item_code | text | FK items |
| quantity | numeric | |
| uom | text | |
| unit_price | numeric | |
| plant | text | FK plants |
| delivered_on_time | boolean | |

**contracts**: rate contract headers from every source. The ceiling baseline for runs comes from here.

| Column | Type | Key / note |
|---|---|---|
| contract_id | text | PK |
| supplier_id | text | FK suppliers |
| supplier_name | text | as written on the contract |
| start_date, end_date | date | |
| value_cap | numeric | |
| consumed_value | numeric | consumed **as at `consumed_as_of`**; 0 for pdf/manual |
| consumed_as_of | date, null | the register date (2026-10-31) for register rows; null for pdf/manual (zero since signing) |
| source | text | check in (register, pdf, manual) |
| source_file | text, null | e.g. `data/contracts/pdf/RC-2026-031.pdf` |
| added_by | text | `seed` for kit rows |
| added_at | timestamptz | |

**contract_lines**: the items and rates each contract covers. A ceiling is shared across all of a contract's lines.

| Column | Type | Key |
|---|---|---|
| contract_id | text | PK part, FK contracts |
| item_code | text | PK part, FK items |
| description, uom | text | |
| rate | numeric | |

## Policy

**policy_versions**: every policy version, whatever its status. The engine reads only approved documents. A database trigger refuses any change to an approved or withdrawn row except approved → withdrawn (and the closing columns), and refuses deleting one (H6).

| Column | Type | Key / note |
|---|---|---|
| id | serial | PK |
| policy_id | text | e.g. CORVO-PROC-POL-04 |
| version | text | unique (policy_id, version) |
| effective_from | date, null | null only for an incomplete draft (the amendment gave no date); approval requires one |
| status | text | check in (draft, approved, discarded, withdrawn) |
| base_version_id | integer, null | FK policy_versions: the approved version the draft started from (the diff is against it) |
| draft_info | jsonb, null | the reviewer lists: `not_expressed`, `translation_notes`; the LLM attempts (provider, model, outcome); the label the model proposed; the draft mode and its operations; seconds taken |
| drafting_status | text | check in (drafting, ready, failed): an AI draft is made in the background (D38); manual and seeded versions are `ready` |
| drafting_started_at / drafting_finished_at | timestamptz, null | when the background drafting started and ended |
| drafting_error | text, null | the plain reason a drafting failed (AI unavailable, unusable reply, more than 5 minutes, server restarted) |
| document | jsonb, null | the whole policy JSON (`docs/policy_schema.md`); empty only while drafting or after drafting failed |
| source_document_name | text, null | uploaded file name, or `chat` |
| source_document_text | text, null | the amendment text as received |
| change_summary | text | |
| drafted_by | text | `seed`, `manual:<name>` or `llm:<model that answered>` |
| impact_summary | jsonb, null | stored **at approval**: the on-demand impact preview the approver saw, i.e. which decisions changed and why, per batch previewed |
| created_by | text | |
| created_at | timestamptz | |
| approved_by | text, null | |
| approved_at | timestamptz, null | |
| closed_by / closed_at / close_comment | text / timestamptz / text, null | who discarded a draft or withdrew an approved version, when and why (a comment is required to withdraw) |

**Which version applies to a requirement:** among the approved versions, the one with the **latest `effective_from` on or before the requirement date**. If two approved versions share that `effective_from`, the one with the **later `approved_at`** wins. An approved document is never edited; a change is a new version. A draft that is never approved stays a draft or is discarded; every step (draft, edit, approve, discard, withdraw, and every LLM failure) is in the audit log. A withdrawn version is no longer used by later runs; runs made under it keep their record.

## Intake

**pr_batches**: one row per uploaded PR batch CSV. It exists because Run 1 and Run 2 must reprocess *the same* batch, and the blind batch may reuse PR numbers from the sample batch.

| Column | Type | Key |
|---|---|---|
| id | serial | PK |
| filename | text | |
| csv_text | text | the file exactly as uploaded |
| csv_sha256 | text | |
| line_count | integer | |
| uploaded_by | text | |
| uploaded_at | timestamptz | |

**pr_lines**: every PR line, from a batch or from chat. Lines are stored even when invalid, so they can be reported as `NOT_PROCESSED`.

| Column | Type | Key / note |
|---|---|---|
| id | serial | PK |
| source | text | check in (batch, chat) |
| batch_id | integer, null | FK pr_batches; set when source = batch |
| pr_no | text | chat PRs are numbered `PR-CH-00001`, … |
| pr_line | text | exactly as given; unique (pr_no, pr_line) where source = chat. Batch lines are **not** unique: a duplicate is stored and reported as NOT_PROCESSED (line check V3) |
| created_at | timestamp, null | exactly as in the CSV (no zone, no conversion); null when unreadable (line check V7) |
| requester, department | text, null | |
| plant | text | **not** an FK: PUN2 must be storable and reported |
| item_code | text, null | **not** an FK: an unknown code is reported, not rejected |
| description | text | |
| quantity | numeric, null | null if blank or unreadable |
| uom | text, null | |
| estimated_unit_price | numeric, null | |
| need_by_date | date, null | |
| urgency | text, null | |
| raw | jsonb | the original row as text, so nothing is lost when a value does not parse |
| created_by | text | |
| ingested_at | timestamptz | |

## Runs and outputs

**runs**: one execution of the engine over one batch, or over the open chat lines. Impact previews are computed on demand and **not** stored as runs.

| Column | Type | Key / note |
|---|---|---|
| id | serial | PK |
| kind | text | check in (batch, chat) |
| batch_id | integer, null | FK pr_batches: the batch processed |
| policy_version_ids | json list | every approved version the run applied (chosen per requirement date) |
| inputs | jsonb | **snapshot**: the PR lines processed, master data, the policy documents applied, and `contract_baseline` (each contract's starting consumed value and cap) |
| inputs_sha256 | text | the same inputs must give the same outputs |
| export_sha256 | text | SHA-256 of the decision CSV as first exported; regenerating it from `decisions` must match |
| engine_version | text | git commit of the code |
| status | text | check in (running, done, failed) |
| error | text, null | |
| started_by | text | |
| started_at, finished_at | timestamptz | |

The run's **output** is the `requirements`, `decisions`, `purchase_orders`/`po_lines` and `sourcing_requests` rows carrying its `run_id`.

**Deterministic IDs within a run.** Requirements are numbered `R-0001`, `R-0002`, … in order of their first line's `created_at`, then `pr_no`, then `pr_line`. POs are numbered `PO-0001`, … in order of their first requirement's `created_at`, then group_id. Both are counters inside the run, so processing the same batch twice gives identical `group_id` and `po_id` values.

**requirements**: clubbed requirements (2.2) and the engine's full explanation. This is the buyer workspace queue. These rows are written once by the run and never updated.

| Column | Type | Key / note |
|---|---|---|
| id | serial | PK |
| run_id | integer | FK runs; unique (run_id, group_id) |
| group_id | text | our requirement ID (export column) |
| item_code | text | resolved code or `NEW` |
| plant | text | |
| requirement_date | date | first line's creation date |
| first_created_at | timestamp | the anchor for consolidation |
| total_quantity | numeric | |
| value_inr | numeric, null | null only for a new item without an estimate (D12) |
| valuation_source | text | which 3.1 source priced it |
| policy_version_id | integer | FK policy_versions |
| rule_id, decision, route | text | |
| supplier_id | text, null | for POs |
| unit_price | numeric, null | |
| suggested_supplier_ids | json list | for sourcing, ranked |
| contract_id | text, null | contract used or relied on |
| relied_on | jsonb | PO numbers and contract used, preferred-list score breakdown, missing fields |
| reason | text | |

**decisions**: exactly one export row per PR line per run, enforced by the primary key (run_id, pr_line_id). The 13 export columns are stored as the **exact text written to the CSV**, in the brief's output format (README, export columns). Regenerating an old run's export is therefore a fixed-order dump of these strings with a fixed CSV dialect, byte for byte, and `runs.export_sha256` checks it.

| Column | Type | Key |
|---|---|---|
| run_id | integer | PK part, FK runs |
| pr_line_id | integer | PK part, FK pr_lines |
| requirement_id | integer, null | FK requirements (null for NOT_PROCESSED) |
| row_order | integer | position in the export (batch file order) |
| pr_no, pr_line, resolved_item_code, group_id, po_id, decision, route, supplier_id, unit_price, group_value_inr, suggested_supplier_ids, policy_version, reason | text | as written to the export |

## Workspace outcomes

**purchase_orders**: consolidated POs (section 7), created by a run. The workflow status is changed only by a buyer action, and each change is also in `buyer_actions` and `audit_log`.

| Column | Type | Key |
|---|---|---|
| id | serial | PK |
| run_id | integer | FK runs; unique (run_id, po_number) |
| po_number | text | `PO-0001`… within the run (export `po_id`) |
| supplier_id | text | FK suppliers |
| plant, route | text | |
| first_requirement_at | timestamp | the 24-hour window anchor |
| total_value | numeric | |
| status | text | check in (proposed, approved, cancelled) |

**po_lines**: one line per requirement placed on the PO.

| Column | Type | Key |
|---|---|---|
| po_id | integer | PK part, FK purchase_orders |
| line_no | integer | PK part |
| requirement_id | integer | FK requirements, unique |
| item_code | text | |
| quantity, unit_price, value | numeric | |

**sourcing_requests**: RFQ, RFP, Capex and new-item requests, never combined (7.2).

| Column | Type | Key |
|---|---|---|
| id | serial | PK |
| run_id | integer | FK runs |
| requirement_id | integer | FK requirements, unique |
| route | text | |
| suggested_supplier_ids | json list | |
| suggest_count_requested | integer | so the screen can say "4 of 5 found" (D9) |
| status | text | check in (proposed, issued, cancelled) |

**buyer_actions**: append-only. Every approval or override sits beside the original decision, and the original is never changed. A requirement's current state is its latest action.

| Column | Type | Key / note |
|---|---|---|
| id | bigserial | PK |
| requirement_id | integer | FK requirements |
| action | text | check in (approve, override) |
| new_route, new_supplier_id | text, null | the buyer's choice (override only) |
| new_unit_price | numeric, null | |
| new_suggested_supplier_ids | json list, null | |
| comment | text, null | required for an override (check constraint) |
| actor, actor_role | text | |
| at | timestamptz | default now() |

## Audit

**audit_log**: append-only (trigger). Every user action and every LLM call or failure, with who and when.

| Column | Type | Key |
|---|---|---|
| id | bigserial | PK |
| at | timestamptz | default now() |
| actor, actor_role | text | |
| action | text | e.g. `batch.upload`, `run.start`, `policy.draft`, `policy.approve`, `buyer.approve`, `buyer.override`, `contract.add`, `llm.failure` |
| entity_type, entity_id | text | |
| comment | text, null | |
| details | jsonb | before/after, the model that answered, the error text |

## Who reads what

| Tables | Read by the engine (through the loader) | Used only by the app |
|---|---|---|
| items, suppliers, plants, po_history | ✓ | |
| contracts, contract_lines | ✓ (as the ceiling baseline, below) | contracts screen |
| policy_versions | ✓ approved documents only | drafts, diff, approval, impact summary |
| pr_lines | ✓ the lines of the run | intake, workspace |
| buyer_actions | ✓ chat runs only: which requirements are already approved (D15) | workspace |
| pr_batches, runs, requirements, decisions, purchase_orders, po_lines, sourcing_requests, audit_log | | ✓ (the app writes the engine's results here) |

The engine itself writes nothing.

## Contract ceiling baseline for a run

- **Where it comes from:** when a run starts, the loader builds each contract's starting consumed value:
  - register contracts: `consumed_value` (as at the register date, 2026-10-31);
  - PDF-only and manually added contracts: **0**.

  These baselines are frozen into `runs.inputs.contract_baseline`.
- **Within the run:** the engine draws ceiling down in requirement-date order (4.2), in memory only. Nothing is written back to `contracts`.
- **Every run** (Run 1, Run 2, any rerun, every chat run, every on-demand impact preview) starts from this same baseline.
- **Approving POs in the buyer workspace does not change the baseline** used by `POST /api/process-batch`, or by any other run (D14, option A). Approval writes `buyer_actions`, sets the PO's workflow status, and logs it. `contracts.consumed_value` is never updated.
- The baseline changes only when the contracts table itself changes (a contract is added on the contracts screen). The run snapshot shows which contracts a run saw.

## Confirmation against the review checklist (2026-11-16)

| Requirement | Where it is true |
|---|---|
| Money and rates are exact decimals, never floats | Types: `numeric` columns, `Decimal` in the loaders and dataclasses |
| PR `created_at` stored exactly as given; windows computed on those values | `pr_lines.created_at` is `timestamp` without zone, with no conversion; the Types paragraph |
| A run stores its batch, baseline, every policy version applied and its full output; old exports regenerate byte for byte | `runs.batch_id`, `inputs` (lines, `contract_baseline`, policy documents), `policy_version_ids`; `decisions` stores the export text, checked by `export_sha256` |
| group_id and po_id are deterministic within a run | "Deterministic IDs within a run" |
| Exactly one decision per PR line per run, enforced by a key | `decisions` PK (run_id, pr_line_id) |
| Which approved version wins on a date | Later `effective_from`; on equal dates, later `approved_at` (Policy section) |
| An override keeps the original and adds the buyer's choice and comment beside it | `requirements` and `decisions` are never updated; `buyer_actions` rows sit beside them |
| The audit log is append-only | Trigger on `audit_log` (and on `buyer_actions`) rejects UPDATE and DELETE |

## Answers recorded (2026-11-16)

1. Approved POs **never** consume contract ceiling (option A). Option B (chat runs see approved CONTRACT_PO value) is a known limitation and next step: DECISIONS.md D14.
2. Approved POs are **not** added to PO history (D14).
3. Each new chat PR triggers a run over all open chat lines, never mixed with batch lines. A line cannot join a requirement a buyer has already approved; it starts a new one (D15).
4. A name and role sent with each request is enough.
5. `pr_batches` is accepted.
6. Impact previews are computed on demand, not stored as runs. The preview summary is stored with the version at approval (`policy_versions.impact_summary`).


## Chat intake (B2, 17 Nov)

**chat_conversations**: one requester's conversation. `state` is the draft PR the code builds (`backend/chat/conversation.py`).

| Column | Type | Key / note |
|---|---|---|
| id | serial | PK |
| user_name, role | text | who it belongs to; only they can read or continue it |
| status | text | check in (open, created, cancelled, policy_draft) |
| state | jsonb | lines (text, item, quantity, unit, new item, price, candidates), plant, need-by, urgency, the question pending |
| pr_no | text, null | the PR it created (`PRC-26-00001`) |
| policy_version_id | integer, null | FK policy_versions: the amendment draft a Procurement user started in chat |
| created_at, updated_at | timestamptz | |

**chat_messages**: every message in order. `sender` in (user, assistant); `payload` holds the choices and card shown, and how a user message was read (`llm:<model>`, `reader`, or `reader (AI unavailable: ...)`).

Chat PR lines are ordinary `pr_lines` rows with `source = 'chat'` and no batch. Chat runs are `runs` rows with `kind = 'chat'` over the open chat lines (D15).


## Workspace (B4, 17 Nov)

`requirements` gains `status` (open, approved, overridden; check) and `row_version` (integer, starts at 1). Approve and Override are conditional updates on both (D42). `purchase_orders.status` becomes `approved` and `sourcing_requests.status` becomes `issued` when approved. Every action is a `buyer_actions` row (append-only) and an `audit_log` row.
