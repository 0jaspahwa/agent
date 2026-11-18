# Applying an amendment through the app's API

The exact sequence used in the practice run (19 Nov, 01:26, local Docker app, Amendment No. 1 → v5.1, about two
minutes of API time), so Thursday is the same steps. Only the app's endpoints are used: never edit
`backend/policies/v5.0.json`, the database or any code to apply an amendment. The policy document is edited as a JSON
file on your machine and sent back with `PUT`; the app validates it, explains it, previews it and stores it.

Commands are Git Bash, run from the repo folder (the kit's sample batch is in `data/` locally; their batch goes in a
folder outside the repo).

## 0. Set up

```bash
B=http://localhost:8000
```
On Thursday: `B=https://corvo-procurement-d2uh.onrender.com` (wake it first: `curl -s -m 120 $B/api/health`).

```bash
WHO=(-H "X-User: Ojas%20Pahwa" -H "X-Role: Procurement")
```
```bash
BATCH=data/pr_batches/sample_pr_batch.csv
```
On Thursday: `BATCH=~/blind/<their batch>.csv`, and `OUT=submission` instead of `dryrun`.

```bash
OUT=dryrun && mkdir -p $OUT
```

## 1. Check the starting state

```bash
curl -s $B/api/health
```
Must show `"kit_loaded": true` and items 73, suppliers 48, po_history 468, contracts 12.

```bash
curl -s $B/api/policies
```
Only `5.0` may be `approved`. Withdraw any other approved version first (step 9).

## 2. Run 1: the batch under v5.0

```bash
curl -s -D $OUT/run1.headers -F "file=@$BATCH" "$B/api/process-batch?format=csv&policy_version=5.0" -o $OUT/run1.csv
```
`policy_version=5.0` records Run 1 as "only version 5.0" (docs/thursday.md step 10). While 5.0 is the only approved
version, leaving it out (by date, as in the practice) gives byte-identical output.

```bash
RUN1=$(grep -i x-run-id $OUT/run1.headers | tr -d '\r' | cut -d' ' -f2) && curl -s $B/api/runs/$RUN1
```
Note the `batch_id` in the reply (`BATCH_ID=...`): the impact preview needs it. Practice: run 3, batch 3, 186 lines.
The sample batch's Run 1 equals `backend/tests/golden/sample_pr_batch_decisions.csv`.

## 3. Create a draft from the current version (no AI)

```bash
curl -s -X POST "${WHO[@]}" -H "Content-Type: application/json" -d '{"from_current": true}' $B/api/policies/drafts -o $OUT/draft_created.json
```
HTTP 201. The reply has the draft's `id` (practice: 2), its proposed `version` label (`5.1`), `effective_from: null`,
and the full `document`, a copy of v5.0. Save the document alone as `$OUT/draft.json` (any JSON tool: take the
`document` field).

## 4. Edit the document, clause by clause

Edit `$OUT/draft.json` with `docs/manual_amendment_cheatsheet.md`: one cheat-sheet snippet per clause, and the
metadata from its section 1. Every clause either becomes an edit or a "NOT EXPRESSED" line in `change_summary`
(section 14). The practice amendment, and what each clause became:

| Clause | Cheat sheet | Edit |
|---|---|---|
| Header: version 5.1, effective 12 Nov 2026 | 1 | `"effective_from": "2026-11-12"`; `version` stays `"5.1"` (the app's label, which the amendment also names); `supersedes` stays `"5.0"`; `source_document` names the amendment; `change_summary` one line per clause |
| 1. CHK1 spot limit 1,50,000 | 3 | append to `overrides`: `{"id": "OV-1", "parameter": "limits.spot_po", "when": {"==": [{"var": "line.plant"}, "CHK1"]}, "set": {"value": 150000, "text": "below 1,50,000 at CHK1"}}` |
| 2. Facility Services to RFQ unless on contract | 6b | insert into `rules` after `5.2`: `{"id": "5.2A", "title": "Facility Services RFQ", "clause_text": "...", "when": {"==": [{"var": "item.category"}, "Facility Services"]}, "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 4}}` |
| 3. 5.3 only with lead time ≤ 7 days | 8b | append `{"<=": [{"var": "requirement.lead_time_days"}, 7]}` to rule `5.3`'s `when.and` list, and extend its `clause_text` |
| 4. Clubbing creation window 10 days | 9a | `parameters.clubbing.creation_window.length`: `10` |
| 5. RFQ suggests 4 | 5 | rule `5.5`: `then.suggest_count` `4`, and its `clause_text` |
| 6. Plant Head approval of POs above 5,00,000 | 14 | NOT EXPRESSED in `change_summary`: an approval step after the decision, not a routing or supplier decision |

## 5. Send it, and read what changes

```bash
curl -s -X PUT "${WHO[@]}" -H "Content-Type: application/json" --data-binary @$OUT/draft_51.json $B/api/policies/drafts/2
```
HTTP 200. Then:

```bash
curl -s "${WHO[@]}" $B/api/policies/2 -o $OUT/draft_view.json
```
Read `errors` (must be `[]`), `warnings`, `incomplete` (must be `false`) and `diff` (the sentences). Practice result,
no errors, no warnings:

- Clubbing creation window: 14 calendar days becomes 10 calendar days
- Rule 5.3 'Emergency PO' changed (when, clause_text): now applies when it is an emergency and requirement value is at or below 5,00,000 (Emergency PO limit) and bought from an Active supplier recently and lead time in days is at or below 7; outcome: EMERGENCY_PO to the 1st preferred supplier at its reference price
- Rule 5.5 'RFQ' changed (then, clause_text): now applies when requirement value is below 10,00,000 (RFQ limit); outcome: RFQ with 4 suggested suppliers
- New override OV-1: limits.spot_po gets text 'below 1,50,000 at CHK1', value 1,50,000 when plant is 'CHK1'
- New rule 5.2A 'Facility Services RFQ' after 5.2: applies when item category is 'Facility Services'; outcome: RFQ with 4 suggested suppliers
- plus the metadata lines: Version '5.0' becomes '5.1', Supersedes, Effective from '2026-04-01' becomes '2026-11-12', Source document, Change summary

Go through the review checklist at the end of the cheat sheet. If anything is wrong, edit the file and `PUT` again
(the same draft; step 5 repeats).

## 6. Preview the impact on the batch

```bash
curl -s -X POST "${WHO[@]}" "$B/api/policies/drafts/2/preview?batch_id=$BATCH_ID" -o $OUT/preview.json
```
Read `explanation`, `lines_under_draft`, `routes_before` / `routes_after`, and each entry of `changes` (line,
changed fields, `rule_before` → `rule_after`, `version_before` → `version_after`). Check that every changed line's
`version_after` is the new version (so its requirement date is on or after `effective_from`), and attribute each to a
clause by its rule. Practice: "16 of 186 lines change", 80 lines under 5.1; EMERGENCY_PO 6 → 4, RFQ 53 → 55.

## 7. Approve

```bash
curl -s -X POST "${WHO[@]}" "$B/api/policies/drafts/2/approve?batch_id=$BATCH_ID"
```
HTTP 200. `curl -s $B/api/policies` now shows the new version `approved`, `approved_by` "Ojas Pahwa".

## 8. Run 2 by requirement date, and the preferred list

```bash
curl -s -D $OUT/run2.headers -F "file=@$BATCH" "$B/api/process-batch?format=csv" -o $OUT/run2.csv
```
No `policy_version`: each requirement uses the version in force on its requirement date (D36). Use
`&policy_version=<new>` only if their instructions say to apply the amendment to the whole batch. Check:

```bash
diff <(cut -d, -f1,2,6-11 $OUT/run1.csv) <(cut -d, -f1,2,6-11 $OUT/run2.csv) | grep -c "^>"
```
equals the preview's changed count (practice: 16), and `cut -d, -f12 $OUT/run2.csv | sort | uniq -c` shows the
versions used (practice: 106 under 5.0, 80 under 5.1).

```bash
curl -s "$B/api/preferred-suppliers/export.csv?as_of=<THEIR_DATE>" -o $OUT/preferred.csv
```
Practice: as of 2026-11-12, 155 rows. No Blocked or Inactive supplier in either file:
`cut -d, -f8,11 $OUT/run2.csv | grep -cE "S004|S008|S011|S031|S034"` and
`cut -d, -f3 $OUT/preferred.csv | grep -cE "S004|S008|S011|S031|S034"` both print 0.

On Thursday the three files are `submission/ojaspahwa__run1.csv`, `ojaspahwa__run2.csv`,
`ojaspahwa__preferred.csv` (docs/thursday.md).

## 9. Practice only: undo it

**Never on Thursday.** After a practice run, withdraw the version so only 5.0 stays approved:

```bash
curl -s -X POST "${WHO[@]}" -H "Content-Type: application/json" -d '{"comment": "practice"}' $B/api/policies/2/withdraw
```
Then `curl -s $B/api/policies`: only `5.0` approved (the practice version shows `withdrawn`, closed by Ojas Pahwa);
the sample batch by date equals the golden file again; `rm -rf dryrun` and `git status` is clean.
