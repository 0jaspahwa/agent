# Thursday 19 Nov: the blind test runbook

Follow the numbered steps in order. Times are IST. `<app>` is the hosted URL. The three output files go in a
folder named `submission` at the top of the repo, with exactly these names (two underscores):

| File | What it is |
|---|---|
| `submission/ojaspahwa__run1.csv` | the decisions CSV of Run 1 (their batch under v5.0) |
| `submission/ojaspahwa__run2.csv` | the decisions CSV of Run 2 (after the amendment is approved) |
| `submission/ojaspahwa__preferred.csv` | the preferred supplier export for their date |

`<THEIR_DATE>` is the as-of date they give for the preferred lists, `YYYY-MM-DD`.

The task kit is not in the repo (task rules). Locally it is in `data/` (the kit's folders, copied by hand); the
hosted app has it in its database, loaded once from the kit zip under **Load kit data** (docs/deploy.md).

Commands are for Git Bash in the repo folder. **After 10:00 commit nothing except files in `submission/`.**

## Before 10:00

1. **08:30 (5 min). The frozen commit.** `git status` shows nothing to commit; `git log --oneline -1` is the commit
   you mean to freeze; `git push`. Note the commit id: it is the frozen app.
2. **08:35 (10 min). Deploy it.** Render → the web service → **Environment**: check `RESET_DB_ON_START` is `false`.
   Then **Manual Deploy → Deploy latest commit**. Wait for `Application startup complete` in **Logs**, and check
   the log has no `RESET_DB_ON_START=true` line.
3. **08:45 (5 min). Health, and the kit is loaded.** `curl -s <app>/api/health` shows `"database": "postgresql"`,
   **`"kit_loaded": true`** and rows `items 73, suppliers 48, po_history 468, contracts 12`. (`contracts` is 12
   unless a contract was added by hand.) If it shows `"kit_loaded": false` or the notice "No kit data loaded":
   open `<app>`, choose a name and **Procurement** → **Load kit data** → choose the kit zip
   (`Cantill_FullStack_Task_Kit_vf.zip`, exactly as received) → **Load kit data**; the page lists the rows added
   (items 73, suppliers 48, PO history 468, contracts 12). Run the `curl` again: `"kit_loaded": true`. Without it
   every batch is refused.
4. **08:50 (5 min). Only v5.0 approved.** `curl -s <app>/api/policies` (as JSON). Every version other than 5.0
   must be `withdrawn`, `discarded` or a `draft` you will not touch. If a rehearsal version is still `approved`,
   withdraw it in the interface (Policy → the version → Withdraw) **now**; otherwise Run 1 by date would use it.
5. **08:55 (5 min). Golden check.**
   `curl -s -F "file=@data/pr_batches/sample_pr_batch.csv" "<app>/api/process-batch?format=csv&policy_version=5.0" -o /tmp/hosted.csv`
   then `git diff --no-index --stat backend/tests/golden/sample_pr_batch_decisions.csv /tmp/hosted.csv`: no output
   means identical. Any output: stop and run locally instead (step 30).
6. **09:00 (5 min). Interface.** Open `<app>`, choose a name and Procurement. Workspace, Batches, Policy and
   Preferred suppliers all open without an error.
7. **09:30 (10 min). Submit the form**: the public GitHub repo URL and `<app>`. Keep the confirmation.
8. **09:55 (1 min). Wake the app.** Free plan: it sleeps after 15 idle minutes. Open `<app>/api/health` and wait
   for an answer (up to a minute) so their first request is fast. Do it again at 10:00 if needed.

## 10:00 Run 1: their batch under v5.0 (target: done by 10:25)

9. **10:00 (5 min). Read their instructions.** Save their files in a folder **outside** the repo (e.g.
   `~/blind/`). Write down: the batch file, the amendment file, `<THEIR_DATE>`, and
   anything they say about how to apply the amendment (see step 21).
10. **10:05 (3 min). Process.** Interface → **Batches** → choose their CSV → Policy: **Only version 5.0** → Process.
    (Before the amendment is approved, "by requirement date" gives the same result; the named version is the safe
    choice and is recorded in the run.) A 200-line batch takes a few seconds.
11. **10:08 (2 min). Download** the decisions CSV from the result card. Note the run number.
12. **10:10 (8 min). Sanity checks on the CSV** (`RUN1=~/Downloads/<the file>`):
    - Row count equals their input lines. Count lines that hold data (blank rows, even ",,,,", are skipped by the
      app): `grep -c '[^,[:space:]]' ~/blind/<their batch>` and `grep -c '[^,[:space:]]' "$RUN1"` give the same
      number (both include the header).
    - No NOT_PROCESSED surprise: `grep -c ",NOT_PROCESSED," "$RUN1"`. In the workspace (Run picker → this run →
      **Not processed** tab) read each reason: a zero quantity, an unknown plant, a missing date are expected; a
      line of good data that is not processed is a surprise to look at (but do not change anything: no code after 10:00).
    - Route counts look plausible: the result card's table. The sample had about 40% spot, 30% RFQ, 18% contract
      PO, 5% each Capex and RFP. A batch that is 100% one route, or has no PO at all, is suspicious.
    - No Blocked or Inactive supplier as a PO supplier or a suggestion (columns 8 and 11; the reason column may
      mention one, e.g. why its contract was not used):
      `cut -d, -f8,11 "$RUN1" | grep -E "S004|S008|S011|S031|S034"` prints nothing.
13. **10:18 (5 min). Commit it.** `mkdir -p submission && cp "$RUN1" submission/ojaspahwa__run1.csv` then
    `git add submission/ojaspahwa__run1.csv && git commit -m "Run 1: <their batch> under policy v5.0 (hosted run N)" && git push`.

## Run 2: the amendment (target: done by 11:15)

14. **10:25 (2 min). Draft it.** Interface → **Policy** → upload their amendment (PDF, DOCX, TXT or MD), or paste
    its text → **Draft with AI**. The page shows "The AI is drafting"; it usually takes under a minute.
    If it says **Drafting failed** (AI busy or down), go to step 18.
15. **10:27 (10 min). Read the draft.** On the draft's page, in this order:
    - **Effective from**: the date the amendment states. "NOT SET" means it gives none: enter one in step 18 only
      if their instructions give it.
    - **What the AI could not express**: every item here is a part of the amendment that is **not** in the draft.
      If it matters to decisions, add it by hand (step 18).
    - **What changes**: read each sentence against the amendment. Each change in the amendment must appear once;
      nothing else may change (a change to a rule's wording only is harmless).
    - **Must be fixed before approval**: must be empty.
16. **10:37 (5 min). Check one line by hand.** Pick one requirement the amendment should affect and one it should
    not. Keep them in mind for step 20.
17. If steps 15 and 16 are right, go to step 19.
18. **(15 min) Correct it by hand.** Either edit the AI's draft, or press **Edit the current version by hand (no
    AI)** for a fresh copy of v5.0. In **Edit the draft (JSON)**:
    - set `"effective_from": "YYYY-MM-DD"`;
    - a limit: `parameters.limits.<spot_po|emergency_po|rfq>`: `"value"` and `"operator"` (`"<"` below, `"<="` at
      or below);
    - a window: `parameters.clubbing.creation_window.length`, `need_by_window.length`,
      `parameters.consolidation.window.length`;
    - a suggestion count: the rule's `then.suggest_count` (rule 5.5 RFQ, 5.6 RFP, 5.1 Capex);
    - a new rule: copy rule 5.4 or 5.5 in `rules`, give it a new `id` (e.g. `"5.3A"`), put it **where the amendment
      says** (rules are tried in order), and change its `when`. Examples to copy:
      plant only `{"==": [{"var": "requirement.plant"}, "CHK1"]}`;
      category `{"==": [{"var": "item.category"}, "Lubricants"]}`;
      value `{"meets_limit": [{"var": "requirement.value_inr"}, "limits.rfq"]}`;
    - a different number for one plant: an entry in `overrides`
      (`docs/policy_schema.md` section 3: `{"id": "OV-1", "parameter": "limits.spot_po", "when": {"==": [{"var": "line.plant"}, "CHK1"]}, "set": {"value": 100000}}`);
    - a fact that does not exist: a `derived_facts` entry (`docs/policy_schema.md` section 4).
    Press **Save and re-check**. Repeat until "What changes" lists exactly the amendment and nothing must be fixed.
19. **10:45 (5 min). Preview the impact** on their batch (Impact preview → their batch → Preview the impact).
    Read the first line:
    - "N of M lines change": expected for an amendment that applies to the batch. Check your two lines from step 16.
    - "**No decision changes: the effective date ... is after the last requirement in this batch**": the amendment
      starts after their batch. Run 2 by date will equal Run 1. That is the policy working as written (D36), not a
      bug. Go to step 21.
    - "No decision changes: N lines fall under the draft ... but what it changes does not alter any of their
      decisions": the amendment applies but this batch has nothing it affects. Re-read step 15 once; if the draft is
      right, this is the answer.
20. **10:50 (2 min). Approve.** **Approve** → confirm. The page shows "approved by <you>".
21. **10:52 (3 min). Process again** under the right policy:
    - **Default: Batches → their CSV → Policy: "The version in force on each requirement date"** (D36).
    - Use **"Only version <new>"** only if their instructions explicitly say to apply the amendment to every line
      of the batch whatever its date (for example "apply the amendment to the whole batch"). Write in the commit
      message which one you used.
22. **10:55 (8 min). Download and check.** Same checks as step 12. Then compare the decisions with Run 1:
    `diff <(cut -d, -f1,2,6-11 "$RUN1") <(cut -d, -f1,2,6-11 "$RUN2") | grep -c "^>"` counts the lines whose
    decision, route, supplier, price, value or suggestions changed. It should match the preview's "N lines change"
    (0 when the preview said no change). Do not compare the `group_id` and `po_id` columns: when one PO disappears,
    every later PO number shifts by one (the dry run showed 4 "changed" rows for 1 real change). If the preview
    counted more lines than this command, the extra ones only changed which lines share a requirement or a PO.
23. **11:03 (5 min). Commit it.** `cp "$RUN2" submission/ojaspahwa__run2.csv`, then
    `git add submission/ojaspahwa__run2.csv && git commit -m "Run 2: <their batch> after amendment <name>, approved as v<new>, processed by requirement date (hosted run N)" && git push`.

## Preferred supplier lists (target: done by 11:30)

24. **11:10 (3 min).** Interface → **Preferred suppliers** → set **As of** to `<THEIR_DATE>` → **Download the CSV**.
    Or: `curl -s "<app>/api/preferred-suppliers/export.csv?as_of=<THEIR_DATE>" -o ~/Downloads/preferred.csv`.
25. **11:13 (5 min). Check it.** First line `item_code,rank,supplier_id,reference_price`; ranks are 1 to 3; no
    Blocked or Inactive supplier (`cut -d, -f3 file | grep -E "S004|S008|S011|S031|S034"` prints nothing).
    It uses the policy version in force on `<THEIR_DATE>`; the ranking weights did not change unless the amendment
    changed them.
26. **11:18 (3 min). Commit it.** `cp ~/Downloads/preferred.csv submission/ojaspahwa__preferred.csv`, then
    `git add submission/ojaspahwa__preferred.csv && git commit -m "Preferred supplier lists as of <THEIR_DATE>" && git push`.

## Final check (before 11:45; the deadline is 12:00)

27. `git status` is clean and `git log origin/main --oneline -3` shows the three submission commits.
28. On github.com, open the repo's `submission/` folder in a browser: the three files are there with the right
    names, and each opens.
29. Nothing else was committed after the frozen commit: `git log --oneline <frozen commit>..origin/main --stat`
    lists only files under `submission/`.

## If the hosted app is down

30. Do not wait more than 10 minutes for Render. Run locally from the frozen commit, with the same data:
    - `git worktree add ../frozen <frozen commit>` and `cd ../frozen` (a clean copy of exactly that commit);
    - `cp -r ../cantil.ai/data data` (the kit is not in the repo, so the worktree has no `data/`; or skip this and
      upload the kit zip under **Load kit data** once the app is running);
    - `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt`;
    - `cd frontend && npm ci && npm run build && cd ..`;
    - `.venv/Scripts/python scripts/dev_server.py` and open http://localhost:8000. It uses a fresh SQLite database
      seeded from `data/` and **no AI**: draft the amendment with **Edit the current version by hand** (step 18).
    - Follow steps 10–26 against http://localhost:8000.
    - Say so in every submission commit message: "produced locally from the frozen commit <id> because the hosted
      app was down (Render error at HH:MM)".
31. The engine alone can also process a batch without any server: `.venv/Scripts/python scripts/run_batch.py
    <their batch> --out run1.csv` (v5.0, Run 1 only).

## Dry run (18 Nov, local, no AI)

The whole runbook was followed on the local app (`scripts/dev_server.py`, fresh SQLite) with the stress batch as
"their batch", amendment A-7 (PDF) as "their amendment", 2026-11-18 as "their date", and `dryrun/` in place of
`submission/` (deleted afterwards).

| Steps | What happened | Time (the app) |
|---|---|---|
| 3–5 | Health right; only 5.0 approved; the sample under 5.0 identical to the golden file | under 2 s |
| 10–12 | Run 1 of 46 lines in 0.2 s; 7 NOT_PROCESSED, each with the expected reason; no Blocked or Inactive supplier | under 1 s |
| 14 | Drafting failed at once with a plain reason (no AI configured), as it would when the AI is down | 2 s |
| 18 | "Edit the current version by hand", rule 5.5 copied as 5.3C after 5.3 with a category condition, effective date set; "What changes" listed exactly the new rule and the metadata | about 20 s of typing |
| 19–20 | Preview: "1 of 46 lines change" (ST-015, laptops, spot PO → RFQ); approved as 5.2 | under 1 s |
| 21–22 | Run 2 by date; 1 decision changed, as the preview said | under 1 s |
| 24–25 | Preferred lists for 2026-11-18: 155 rows, ranks 1–3, no Blocked or Inactive supplier | under 1 s |

**Fixed in this runbook after the dry run:**
- **Step 12, row count:** the test file ends with a row of commas; the count now ignores blank rows.
- **Step 22, comparing Run 1 with Run 2:** it counted 4 changed rows for 1 real change, because removing one PO renumbers the later PO ids. The check now compares only the decision columns.
- **Steps 12 and 25, Blocked suppliers:** the check looked at every column, so a reason that mentions a Blocked supplier would have raised a false alarm. It now checks only the supplier columns.

On the hosted free plan the app is slower and may need up to a minute to wake (step 8). Allow about 1 hour 15
minutes of your own time for steps 9–29 if nothing goes wrong, which leaves 45 minutes of the two hours spare.
