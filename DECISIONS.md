# DECISIONS

Where the policy (v5.0) or the data is silent or ambiguous, each entry records **what we noticed**, **what we
decided** and **why**, with the evidence. Entries are grouped by theme; the D numbers are the ones used in the code,
the tests and the commit history. Each ends with its status (who confirmed it and when).

## The ten decisions that most affect the results

| | Decision | Effect on Run 1 and Run 2 |
|---|---|---|
| D24 | Preferred ranking: 1·POs + 5·recency + 2·contract + on-time/100 + quality/5, fitted to all 12 orderings in the kit | Which supplier gets every spot and emergency PO, and the order of every suggestion list |
| D2 | Valuation (3.1b) counts POs with suppliers now Blocked or Inactive; they still never get a PO or a suggestion | Requirement values, so which limit a requirement falls under |
| D1 | "Most recent PO" ties go to the highest PO number | Values and reference prices where two POs share a date |
| D3, D8 | History windows: the requirement date itself is excluded, exactly 365 or 548 days back is included | Values, "bought from an Active supplier" and the preferred lists at the window edges |
| D4–D6 | Every "within" is inclusive: clubbing at exactly 14 days and 7 days, consolidation at exactly 24 hours | Which lines form one requirement and which requirements share a PO |
| D22 | Each later line is compared with a requirement's first line; it joins the earliest it can | Requirement membership and values (Ex 14) |
| D20, D21 | Deterministic matching with number and word gates; a weak or tied match becomes a new item with its candidates named | Which item a free-text line is, or NEW_ITEM_SOURCING |
| D9, D13 | Suggest as many eligible suppliers as exist, never padded; equal scores by supplier id | Suggestion lists (Ex 11 has 4, not 5; Ex 12's tie) |
| D10, D11 | The emergency limit is "at or below", spot and RFQ "below"; all arithmetic exact, values rounded half up to paise | Every route at a limit's boundary |
| D36 | Run 1 under v5.0; Run 2 decides each requirement by the version in force on its requirement date | Whether, and from which date, the amendment changes Run 2 |

---

# Data quality and input files

## D17. Forgiving batch reader; a bad cell fails only its own line

**What we noticed.** The blind batch is a new file whose formatting we have not seen.

**What we decided.**
- **Accepted:** a byte-order mark, either line ending, columns in any order, extra columns, header names in any case with stray spaces, and blank rows. Every cell is trimmed.
- **Timestamps** may have seconds, and may use a `T` or a space.
- **A bad cell fails only its own line.** A blank or unreadable cell becomes empty, and the line checks report that line as `NOT_PROCESSED`. That includes an unreadable `created_at` (line check V7).
- **The whole batch is rejected only when the file itself is unreadable:** a required column is missing, the file is empty, it has a header but no lines, or a quoted field is never closed (which would otherwise swallow the rest of the file into one line; found in the break-it pass, `docs/break_it.md`). Required columns: `pr_no`, `pr_line`, `created_at`, `plant`, `description`, `quantity`, `need_by_date`. Optional columns: `requester`, `department`, `item_code`, `uom`, `estimated_unit_price`, `urgency`.
- **Case-insensitive comparison:** plant codes, item codes, units and urgency. Their original text is kept.
- **`pr_line` is kept as text**, exactly as given; ordering uses its numeric value.

**Why.** Losing a whole blind-test batch to one malformed cell would cost every decision in it. A reported line costs one.

*Status: **confirmed** by Ojas, 2026-11-16.*

## D19. Line checks and flags beyond the policy

**What we noticed.** Policy 1.1 and 1.2 assume every line is well formed. A new batch may contain lines that cannot be decided: duplicates, a missing need-by date, a unit that is not the item's unit, a quantity that is not a number, or an unreadable creation time. Other lines are decidable but deserve a note.

**What we decided.** All of these are policy data in v5.0.json, each with its own id and text, so an amendment can change them.
- **NOT_PROCESSED**, with every reason that fired:
  - **V3 duplicate:** a later line with the same `pr_no` + `pr_line` (case and spaces ignored). Only the first in file order is processed.
  - **V4:** need-by date missing or unreadable. Clubbing (2.2) needs it.
  - **V5:** the unit differs from the matched item's unit after case and punctuation are ignored. Quantity × price would be wrong, and we do not convert units.
  - **V6:** quantity missing or not a number.
  - **V7:** creation time missing or unreadable (D17).
  - V1 now covers zero or negative quantities only; V2 is unchanged.
- **Flags**, which never stop the line and travel to the reason text:
  - **F1:** need-by earlier than the creation date.
  - **F2:** urgency blank or unrecognised, treated as Normal.
  - **F3:** item code not in the item master; the description is matched instead.
  - **F4:** item code and description clearly disagree; the code is trusted (policy 1.1: "if the requester gave an item code, use it").
  - **F5:** the description says urgent but the urgency field does not (D45: trust the field).
  - **F6:** unit missing; the item's unit is assumed.
- **Which policy version checks a line:** the version in force on its creation date. If the creation time is unreadable, the latest approved version is used, so the line can still be reported. A line dated before every approved version is NOT_PROCESSED (`NO-POLICY`).

**Why.** A line that cannot be valued or clubbed correctly must not silently produce a decision. A line that can be decided should not be blocked by a cosmetic problem, but the buyer should see it.

*Status: requested by Ojas, 2026-11-16; the specific ids, texts and the latest-version rule for unreadable times are ours.*

## D27. Possible duplicate lines are flagged, not removed

**What we noticed.** PR-26-00174 and 00175 have the same requester, item, plant, quantity and need-by date, 4 minutes apart, under two departments. That looks like the same need entered twice. Policy 2.2 clubs them; nothing in the policy removes them.

**What we decided.** Flag F7 (policy data) marks both lines when the requester (ignoring case), item, plant, quantity and need-by date are all equal and the two were created within `intake.possible_duplicate_window` (30 minutes, inclusive) of each other. Each line's flag names the other. The flag changes no decision: the lines are still clubbed, valued and routed together. It appears in the reason text and, later, on the buyer screen. A line without a requester is never flagged, because nothing ties it to another person's line. Exact repeats of pr_no + pr_line remain NOT_PROCESSED (V3, D19).

**Why.** Removing a line on a guess would be a silent decision. A buyer can confirm a real duplicate with one look.

*Status: **confirmed** by Ojas, 2026-11-16.*

## D26. The worked examples' PO numbers are ours minus one

**What we noticed.** Our PO ids, numbered in creation order (D6, F5), are each exactly one higher than the numbers printed in the worked examples:

| Example | Printed | Ours |
|---|---|---|
| 5 | PO-0001 | PO-0002 |
| 6 | PO-0002 | PO-0003 |
| 4 + 14 | PO-0003 | PO-0004 |
| 1 | PO-0011 | PO-0012 |
| 7 | PO-0023 | PO-0024 |
| 8 | PO-0024 | PO-0025 |
| 2 | PO-0072 | PO-0073 |

The offset is constant through PO-0072, so every PO decision and consolidation in between agrees. The extra PO is our PO-0001, requirement R-0001: PR-26-00174 + 00175. These are two 1-unit servo drives (ITM-1033) at PUN1 from the same requester, 4 minutes apart, with the same need-by date. Clubbed (2.2), they are worth 2 × 65,837.89 = 1,31,675.78, below the spot limit, and S020 is bought from: a spot PO.

**What we decided.** Keep our numbering. A strict expected-failure test (`test_printed_po_numbers_exactly`) records the printed numbers, so any change to it is noticed.

**Why.** PR-26-00170 to 00175 are trap rows appended at the end of the file: two new items, a zero quantity, an unknown plant and this pair. 00174/00175 are the only trap rows that produce a PO, so the printed numbers were most likely produced without them. Under the policy they club into a spot PO. Unclubbed, each would still be a spot PO, and the two would be consolidated anyway. No reading we found makes them anything but a PO. They now carry the possible-duplicate flag (D27), so a buyer sees them.

*Status: **confirmed** by Ojas, 2026-11-16.*

## D16. Export number format

**What we noticed.** The worked examples print rupees with Indian grouping and rounding (1,37,531), but the export is read by a program and compared field by field.

**What we decided.** In the decision CSV, `group_value_inr` is written as plain digits with exactly 2 decimals and no grouping (`137530.65`, not `1,37,531`). `unit_price` is written exactly as it appears in its source (the contract rate, or the PO price, as in the kit file).

**Why.** Exact and machine-readable; the worked examples' rupee figures are display rounding.

**How numbers are written (added with the API, 2026-11-16).** Prices, quantities and scores are written in their shortest exact form: 9168.71, 365, 41415.6, 61. The database stores numeric columns at a fixed scale and returns 365.00 where the kit file says 365. Writing the shortest form makes the database path and the kit path produce the same bytes. The value is the same as in the source; only a trailing zero in the source text is not kept. The kit has three PO prices and three estimates written like "181.0", and these print as 181. Money values (`group_value_inr`, ceilings) always have 2 decimals.

*Status: **confirmed** by Ojas, 2026-11-16.*

## D45. Smaller observations and how each is handled

**What we noticed, and what we decided**, for points too small for their own entry:

| What the data shows | Decision | Why |
|---|---|---|
| 4 lines say "urgent" in the description, but their urgency field is Normal | Trust the field; flag F5 for the buyer | The field is the structured answer; a word in free text is not an emergency declaration |
| Quantity 0 (PR-26-00172) and an unknown plant PUN2 (PR-26-00173) | NOT_PROCESSED, line checks V1 and V2 | Neither can be valued or routed |
| Noise in descriptions ("as per sample", "for maintenance", "(repeat)") | Stripped before matching (D20); "(repeat)" lines club normally | The noise names no item; a repeat is still a requirement |
| The supplier master's on-time % differs from on-time computed from PO history | Use the master's figure | The worked examples use it |
| 5 items have no PO history at all (6 none in the last 365 days) | Valued at the standard price (3.1c); never "bought from an Active supplier", so RFQ or RFP | 3.1(c) and 5.3/5.4 say so |
| An emergency that fails 5.3 (too large, or no Active purchase history) | Falls through to 5.4–5.6, never to "emergency PO anyway" | Rules are tried in order; 5.3's conditions are all required |
| A requirement dated before an amendment's effective date | Decided by the version in force on its requirement date; the impact preview says when nothing changes | D36 |
| The brief says about 525 POs; `po_history.csv` has 468 | Use the file | The file is the data |
| Two kit contracts have no register row (RC-2026-031 and RC-2026-033) | Read from their PDFs, nothing consumed, valid from their start dates (the PR-26-00036 trap) | Policy 4.2 and 4.4 |

*Status: confirmed by Ojas, 2026-11-16.*

## D46. The stress batch, and what the kit cannot test

**What we noticed.** The blind batch "is different from anything in the kit", so we wrote a second batch
(`backend/tests/fixtures/stress_batch.csv`, 46 lines) for the cases the sample does not exercise: clubbing at exactly
14 days and 7 days, consolidation at exactly 24 hours and 24 hours plus one second, a contract emptied exactly,
two contracts competing as one runs out, PDF-only contracts the day before and on their start dates, emergencies
that fail 5.3, Capex, new items, malformed lines and more. Its expected outcomes were worked out by hand from the
policy and the CSV files (`scripts/stress_facts.py`, which imports no engine code), before running the engine.

**What it found.** All 46 lines match. The first comparison showed 6 mismatches, all in our expectations (lines
clubbed into one requirement necessarily share its PO); no engine change was needed. One case the brief asks for
cannot be built from the kit: **no item's only purchase history in the window is with a Blocked supplier.** The
nearest is the safety helmet (ITM-1049), whose only history is with Inactive S031; it is in the batch, and it is
decided by Active S029's contract. Blocked-supplier handling is covered instead by ITM-1006 (whose only contract is
Blocked S004's: never used, never suggested) and by D2.

**What we decided.** Keep the batch and its expectations as a test (`backend/tests/test_stress.py`); it becomes a
second golden file once Ojas approves it. Separately, 200 generated batches are checked for invariants (no crash,
one row per line, PO rows only to allowed suppliers, no ceiling exceeded, order-independent output;
`backend/tests/test_robustness.py`).

**Why.** Expectations derived from the engine would only show that the engine agrees with itself.

*Status: **confirmed** by Ojas, 2026-11-18; the export is the second golden file
(`backend/tests/golden/stress_batch_decisions.csv`).*

## D47. The task kit is not in the repo; what counts as a task data file

**What we noticed.** The task rules say the public repo "must not contain the task data files", but the app was
built to seed from a copy of the whole kit in `data/`, and our own stress batch lived there too.

**What we decided.**
- **Task data files = every file distributed in the kit**: the six CSVs, the twelve contract PDFs, the sample PR
  batch, and the brief, policy and worked-examples PDFs and README. None of them is in the repo or the Docker image:
  `data/` is gitignored and in `.dockerignore`. A check compares the SHA-256 of every tracked file with every file in
  the kit folder and the kit zip (also with other line endings): no copy.
- **Our derived files stay**, because each is our own work about the kit rather than a copy of it:
  `backend/policies/v5.0.json` (our reading of the policy as data; it is the policy, not a data file),
  the golden decision exports (our engine's reviewed output), the frontend fixtures (recorded API responses),
  our stress batch and its expectations (`backend/tests/fixtures/`), the rehearsal amendments, and the docs. Some
  of them name kit facts (item codes, supplier ids, contract file names), which they need to explain or test a
  decision.
- **Two ways to provide the kit:** its folders in `data/` (seeded on start; Docker mounts `./data` read-only), or
  an upload of the kit zip as distributed, a zip without its top folder, or the individual files, under **Load kit
  data** (Procurement; `POST /api/admin/load-kit`). The upload runs the same seed code, in one transaction; a missing
  file (any of the six CSVs, or a contract PDF the register lists) is refused with its name; loading the same kit
  again changes nothing; the sample batch in the zip is never loaded or stored.
- **Without the kit** the app starts with empty master data, logs it, shows "No kit data loaded. Procurement: load it
  under Load kit data." on every screen and in `/api/health` (`"kit_loaded": false`), and refuses to process a
  batch (409): decisions against no items or suppliers would all be wrong.
- **Tests and CI:** every test that reads the kit skips with "kit data not present: put the kit in data/"; CI runs
  the rest. The golden-file checks through the Docker container run locally only (CI checks instead that the image
  starts without the kit and contains no kit files).

**Why.** It follows the rule exactly while keeping every decision reproducible: the evaluators have the kit, and the
hosted app gets it once from the same zip they distributed.

*Status: decided by Ojas, 2026-11-19 (his instruction).*

---

# Item matching

## D20. How a free-text description is matched to an item

**What we noticed.** Policy 1.1 says to match short forms to the item master ("brg 6205 2rs" → Ball bearing 6205-2RS), but not how. Of the sample batch's 186 lines, 39 have no item code. Their variations are lower case, abbreviations (brg, hyd, pneu), noise ("as per sample", "for maintenance", "(repeat)", "- urgent"), an inch mark (`24"`), a trade synonym ("welding rod" for electrode) and a changed word order.

**What we decided.** A deterministic matcher (`engine/matching.py`). Every setting is policy data under `parameters.matching`.
1. **A valid item code wins.** Policy 1.1: use the code if given.
2. **Normalise the description:**
   - lower case;
   - inch marks become "inch", and the "x" between dimensions is dropped;
   - noise phrases are removed;
   - text is split at punctuation and at letter/digit boundaries;
   - abbreviations are expanded.
3. **Number gate:** every number in the description (size, part number, grade) must also be in the item. Numbers are never fuzzy, so 6206 ≠ 6205, M12 ≠ M10, i7 ≠ i5 and 5mm ≠ 3mm.
4. **Word gate:** at least 75 % of the description's words must be found in the item. Words may be fuzzy (similarity ≥ 0.8, words of 4+ letters) to tolerate typos ("safty shoes").
5. **Score:** shared tokens, Dice style, with numbers counting double, because part numbers identify an item more than words do. The best item must reach **0.6**.

**Why these numbers.** They reproduce all 39 free-text lines (37 matched, 2 new), every coded line's own item with its code hidden, and every item master description. They reject the hard negatives.

The two gates exist because the item master has near twins: "Cutting wheel 14 inch" and "Grinding wheel 4 inch". Without the word gate, "cutting wheel 4 inch" matched the grinding wheel. Without number weighting, "brg 6205" (a unique part number) fell below the threshold. Lowering the threshold instead would let a lone generic word such as "oil" match whichever oil item is shortest.

**Second pass for purpose clauses (added 2026-11-16).** Requesters add why they need something: "MS sheet 3mm 1250x2500 for fabrication", "ball bearing 6205-2RS for conveyor line 3", "nitrile coated gloves - for paint shop".
- **When it runs:** only if the full description gives no match. The full text always goes first, because an item name can contain a marker ("Encoder for CNC spindle (Vertex)").
- **What is removed:** text in brackets, or a trailing clause after `for`, `as per` or `against`, or after a spaced `-` or `/` followed by a word. The removal tried first is the shortest.
- **Settings:** the markers are policy data in `matching.purpose_clause`.
- **Never inside a token:** a dash or slash within a token (6205-2RS, V-belt, 5/2) is not a marker.
- **Gates still apply:** the number gate applies in both passes, so "MS sheet 5mm 1250x2500 for fabrication" stays new. The word gate also applies, so "laptop bag for i5 laptop" stays new.

*Status: **confirmed** by Ojas, 2026-11-16, with the second pass for purpose clauses.*

## D21. Ambiguous or weak descriptions become new items, with candidates named

**What we noticed.** A description can match no item well ("flux capacitor"), or two items equally well ("hex bolt" is both M10x40 and M16x60). Policy 1.1 does not say what to do with a weak or tied match.

**What we decided.**
- **Below the 0.6 threshold:** new item. The explanation names up to three closest items, for the buyer and the chat.
- **Two or more items equally good** (top scores within 0.02, and at least 0.3): **ambiguous**, also treated as a new item, with every tied item named. Examples: "gloves" (cotton or nitrile), "hex bolt" (M10x40 or M16x60), "MS sheet 1250x2500" (2mm or 3mm).
- **Never guessed.** The engine never picks one of two equally good items.

**Why.** Picking one of two equally good items is a coin toss that produces a confident wrong decision. A new item goes to sourcing with no PO, and the buyer sees which items were close. The chat will use the same candidates to ask "which one?".

*Status: requested by Ojas, 2026-11-16 (new item, candidates named); the 0.02 margin and 0.3 floor are ours.*

---

# Clubbing and PO consolidation

**How the window boundaries were checked (D4–D8).** The policy states several windows without saying whether the end point counts. `scripts/data_questions.py` (the "boundary check" sections) resolves the sample batch's free-text lines with a crude matcher and clubs lines per 2.2 under every reading. It then lists every pair of lines, every requirement and every PO that sits on or within one unit of each boundary. The clubbing it produces matches worked examples 3, 5 and 14. In general the policy writes **"below"** where a limit is strict (5.4, 5.5) and **"within"** or **"at or below"** for windows and the emergency limit. We read every "within" as **inclusive** (confirmed by Ojas, 2026-11-16). Every window below is a policy parameter with an explicit `inclusive` flag (see `backend/policies/v5.0.json`), so an amendment can change it without code.

## D4. Clubbing: created "within 14 calendar days of the requirement's first line"

**What we noticed.** This can be read as calendar dates (14 dates on) or elapsed time (14 × 24 h from the timestamp), and day 14 may or may not join. No worked example sits near 14 days. In the sample batch, three same-item, same-plant pairs are exactly 14 calendar days apart: PR-26-00124/00125, PR-26-00019/00169-3 and PR-26-00100/00077. All three fail the need-by test anyway (22, 17 and 15 days apart). The 00019/00169-3 pair is 14 calendar days but only 13 d 20 h 40 m elapsed. The closest pair that passes need-by is PR-26-00085/00120 (copper cable, PUN1): 15 calendar days apart, so it is excluded under every reading. Clubbing the batch under all four readings gives **identical** requirements.

**What we decided.** Compare calendar dates: a line joins if `created_date(line) − created_date(first line) ≤ 14` days, so day 14 joins. Parameters: `clubbing.creation_window = {days: 14, unit: "calendar_days", inclusive: true}`.

**Why.** The policy says "calendar days", which counts dates, not hours. "Within" is inclusive, by contrast with the policy's "below". The sample batch does not depend on the choice.

*Status: **confirmed** by Ojas, 2026-11-16. Not settled by any worked example.*

## D5. Clubbing: need-by "within 7 days (either side) of the first line's need-by date"

**What we noticed.** Need-by values are dates, so the only question is whether exactly 7 days joins. Worked example 14 settles the neighbouring cases but not 7 itself. PR-26-00035 (need-by 11-17) does **not** join the requirement whose first line has need-by 11-25 (8 days), and **does** join the one with need-by 11-12 (5 days). Ex 5 joins at 4 and 2 days. No same-item, same-plant pair in the sample batch is exactly 7 days apart. Several are at 6 or 8 days, and they behave the same under both readings. Clubbing under `≤ 7` and `< 7` gives identical requirements.

**What we decided.** `|need_by(line) − need_by(first line)| ≤ 7` days joins. Parameter: `clubbing.need_by_window = {days: 7, inclusive: true}`.

**Why.** "Within 7 days" is inclusive. Ex 14 is consistent with this (8 excluded, 5 included).

*Status: **confirmed** by Ojas, 2026-11-16. Ex 14 confirms the anchor and the 8-day exclusion; exactly 7 joins by our reading.*

## D6. PO consolidation: "raised within 24 hours of the first requirement on that PO"

**What we noticed.** Four pairs of same-plant requirements in the sample batch have first lines **exactly 24 h 00 m apart**:
- PR-26-00055 / 00053
- PR-26-00099 / 00053
- PR-26-00011 / 00166-1
- PR-26-00011 / 00166-3

In every pair the two items share no possible Active supplier (by PO history or contract), and 00166-3 is a Capex item, so it goes to sourcing. None of them can share a PO, and the reading makes no difference in the sample batch. Ex 14 consolidates requirements 20 h 25 m apart (11-02 14:05 and 11-03 10:30), which is not near the boundary. The density of exact 24 h gaps suggests the blind batch may test this.

**What we decided.** A requirement joins an open PO if `created_at(its first line) − created_at(first line of the PO's first requirement) ≤ 24 h`, so exactly 24 h joins. The anchor is the PO's first requirement, not the previous requirement (7.1). Parameter: `consolidation.window = {hours: 24, inclusive: true}`.

**Why.** "Within" is inclusive, as in D4/D5. Timestamps have minute resolution, so exactly 24 h is a real case.

*Status: **confirmed** by Ojas, 2026-11-16: compare timestamps, exactly 24 h joins, measured from the first requirement on the PO. Not settled by any worked example.*

## D22. Clubbing details the policy leaves open

**What we noticed.** Policy 2.2 gives the windows and "the earliest" requirement, but not the order lines are taken in, how text is compared, which version's windows apply when a requirement spans a version change, or how requirements are numbered.

**What we decided** (`engine/clubbing.py`; all windows, keys and orders come from the policy):
- **Order.** Lines are taken in `clubbing.order_by` order: creation time, then PR number, then line number, where line 2 comes before line 10. If an amendment changed `order_by` mid-batch, the order of the latest version among the batch's lines is used, because one batch needs one order.
- **Compared with the first line only.** A line is compared with each requirement's *first* line (Ex 14). If it could join several requirements, it joins the earliest one created.
- **Each requirement keeps its own version.** A requirement uses the policy version in force on its first line's creation date, with that version's overrides evaluated on the first line (line and matched item only). Every line that joins it is judged by those windows, even if the line itself falls under a later version.
- **Comparing the key fields.** `match_on` fields are compared on canonical values: the resolved item code, the plant in upper case, and other text case-insensitively.
- **What never clubs.** New items (rule 1.2) and NOT_PROCESSED lines.
- **Ids.** Requirements are numbered `R-0001`, … in order of the first line's creation time, then PR number, then line number. The same batch always gives the same ids, whatever the file order.

**Why.** Each point is the most literal reading of 2.2 and 2.3, and is fully deterministic. Policy 2.2 says a line joins "the earliest" requirement it qualifies for.

*Status: **confirmed** by Ojas, 2026-11-16.*

## D15. Chat PRs club with each other, never with batch lines or approved requirements

**What we noticed.** Splitting a requirement to stay under a limit (2.1) is just as possible through chat as through a batch. Chat PRs arrive one at a time, though, and a buyer may already have approved an earlier one.

**What we decided.** Each new chat PR triggers a chat run over all open chat lines, so clubbing (2.2) applies across chat PRs too. Chat lines never club with batch lines. A line cannot join a requirement a buyer has already approved; it starts a new requirement, even if it would otherwise club.

**Why.** An approved requirement may already be a PO with a supplier. Silently adding quantity to it would change an approved order. Starting a new requirement keeps the approval intact, and the new requirement is valued and routed on its own.

*Status: **confirmed** by Ojas, 2026-11-16.*

---

# Valuation, history windows and routes

## D1. Two POs on the same most-recent date at different prices (valuation 3.1b, reference price 6.3)

**What we noticed.** `po_history.csv` has dates but no times, so "the most recent PO" can be a tie. There are 4 same-item, same-date ties with different prices in the file. Worked example 11 (ITM-1034, CHK1, requirement date 2026-11-04) depends on one of them: it values the requirement at 20,70,780 / 50 = **41,415.60**.

| file row | po_number | po_date | supplier | qty | unit_price | plant |
|---|---|---|---|---|---|---|
| 275 | 7300215 | 2026-04-10 | S020 | 2 | 40,929.88 | CHK1 |
| 276 | 7300220 | 2026-04-10 | S020 | 2 | 41,415.60 | PUN1 |

Candidate tie-breaks tested against Ex 11:

| Tie-break | Picks | Result |
|---|---|---|
| Highest PO number | 41,415.60 | consistent |
| Last in file order | 41,415.60 | consistent |
| Highest price | 41,415.60 | consistent |
| Lowest PO number / first in file / lowest price | 40,929.88 | ruled out |
| Same plant as the requirement (CHK1) | 40,929.88 | ruled out |
| Average of the tied POs | 41,172.74 | ruled out |
| Largest quantity / supplier / on-time flag | (both rows equal) | cannot separate |

The three survivors cannot be told apart by any worked example. Across the whole file they disagree on 2 of the 4 ties (ITM-1003 on 2026-04-05, where the higher price is from Blocked S004; ITM-1039 on 2026-09-23). "Last in file order" and "highest PO number" are the same thing in this data: the file is sorted exactly by (po_date, po_number). PO numbers are **not** chronological across dates, though: in 241 of 467 adjacent pairs sorted by PO number, the higher number has the earlier date. The numbers look like they were assigned in blocks per item.

The only tie that is the most recent PO for a requirement dated anywhere in November 2026 is ITM-1034 / 2026-04-10, and all three survivors agree on it. The same tie also sets S020's reference price (6.3) for ITM-1034 in the preferred-list export. With the kit's PO history, the choice therefore changes **no** November decision.

**What we decided.** Break ties by the **highest PO number** (unique in the file). The same rule applies wherever "most recent PO" is used: valuation (3.1b) and reference price (6.3).

**Why.** It reproduces Ex 11. "Most recent" is about time, and within a single date the PO number is the only ordering signal the data has. It is a property of the PO itself, so it stays stable if the CSV is re-sorted or loaded from a database (file order would not). "Highest price" also fits Ex 11, but nothing in the policy's wording points to price, so we did not use it. If the blind test ships a different PO history, the two remaining disagreeing ties show where this choice would matter.

*Status: **confirmed** by Ojas, 2026-11-16.*

## D2. Does valuation (3.1b) count POs placed with suppliers now Blocked or Inactive?

**What we noticed.** 58 of the 468 PO rows are with suppliers now Blocked (S004, S008, S011) or Inactive (S031, S034). Policy 3.1(b) says "the most recent PO for the item in the 365 days before the requirement date" with **no** supplier-status qualifier. Rules 5.3/5.4 ("bought from an Active supplier") and 6.1 ("every Active supplier") do qualify it.

**The worked examples do not settle it.** We checked every example valued under 3.1(b)/(c): Ex 5, 6, 7, 8, 9, 10, 11, 12. Each one gives the same value either way, because none of those items has a Blocked/Inactive PO as its most recent PO in the window. Ex 10 (aluminium plate, valued at the 365 standard price) might look relevant, but ITM-1006 has **no PO history at all**, so it says nothing on this question. Examples 1–4 and 14 are valued at a contract rate (3.1a) and Ex 13 at the requester's estimate (1.2), so the question cannot reach them.

**Where it matters in the sample batch.** As of 2026-11-02, five items have a Blocked/Inactive PO as their most recent PO:

| Item | Latest PO (all suppliers) | Latest Active PO | Sample batch effect |
|---|---|---|---|
| ITM-1014 Hex bolt M16x60 | 23.06 (S008 Blocked) | 26.26 | None: RC-2026-015 applies but is out of ceiling, so 3.1(a) values it at the 20.64 contract rate |
| ITM-1049 Safety helmet | 217.81 (S031 Inactive) | 222.14 | None: RC-2026-007 applies, contract rate 191.31 |
| ITM-1017 Argon cylinder | 1,479.06 (S011 Blocked) | 1,614.13 | PR-26-00069 + 00091 (CHK1, clubbed, 382 CYL): 5,65,001 vs 6,16,598; RFQ either way |
| ITM-1020 Cutting wheel 14" | 212.46 (S011 Blocked) | 210.17 | PR-26-00058 (CHK1, Emergency, 2000): 4,24,920 vs 4,20,340, EMERGENCY_PO either way; PR-26-00122 (PUN1, 4100): 8,71,086 vs 8,61,697, RFQ either way; PR-26-00172 is qty 0, NOT_PROCESSED |
| ITM-1050 Safety goggles | 129.55 (S031 Inactive) | 120.38 | PR-26-00083 (CHK1, 180): 23,319 vs 21,668, SPOT_PO either way; PR-26-00060 (CHK1, Emergency, 820, not clubbed: need-by 18 days apart): 1,06,231 vs 98,712, EMERGENCY_PO either way |

So in the sample batch the question changes `group_value_inr` on **5 requirements (6 lines)** and **no route, supplier or PO price**. The PO price comes from the preferred supplier's reference price, not from the valuation. The clubbing and values above were worked out by hand, not by the engine.

**What we decided.** Count **all** POs for the item, whatever the supplier's current status, when valuing under 3.1(b). Store this as a policy parameter (`valuation.include_non_active_suppliers: true`) so an amendment can flip it without a code change.

**Why.** The policy says "Active supplier" in every place where supplier status matters (4.1, 5.3, 5.4, 5.7, 6.1, 6.4) and leaves it out of 3.1(b). Reading the gap as deliberate is the most literal reading. Valuation also estimates what the requirement is worth, and the price actually paid on a recent PO is valid market evidence even if that supplier has since been blocked. Blocked suppliers still never receive a PO or a suggestion (5.7), and they never count as "bought from an Active supplier". The counter-argument: a blocked supplier's price may be unrepresentative, for example cheap because quality was poor. We note it, but it is not strong enough to override the wording. In the sample batch the choice cannot change a route.

*Status: the examples leave this open. **Confirmed** by Ojas, 2026-11-16, as a judgment call.*

## D3. Boundary of "in the N days before the requirement date"

**What we noticed.** PO dates have no time. "In the N days before" could include or exclude a PO dated on the requirement date itself, and the start boundary could be N or N−1 days back.

**What we decided.** The window is `requirement_date − N days ≤ po_date < requirement_date`: a PO on the requirement date itself is excluded, because it was not placed *before* it. The same applies to the 548-day window. The scripts use this; see D8 for which data sits on this boundary.

**Why.** "Before" excludes the day itself; counting back exactly N days keeps "365 days" a full year. `backend/tests/test_history_windows.py` pins both edges on a real PO: the requirement date itself is out, exactly 365 days back is in, 366 is out.

*Status: **confirmed** by Ojas, 2026-11-16; tested 2026-11-18.*

## D8. History windows (365 and 548 days) and the ranking's recency buckets

**What we noticed.** D3 fixes the window as `req − N ≤ po_date < req`. In the sample batch, as of each requirement date and of 2026-11-01:
- **365 days:** six POs sit within one day of the boundary. None changes anything. Where a PO is inside, it is neither the latest PO nor the only Active PO. Where it is just outside (366 days), later POs exist, so counting it would change nothing.
- **548 days:** no PO is near the boundary. 548 days before 2026-11-01 is 2025-05-02, before the PO history starts (2025-06-01), so for any November 2026 date the 548-day window holds the whole history. It cannot matter with this data.
- **Recency buckets (1 = within 90 days, 0.5 = within a year):** one Active item/supplier pair is near an edge. ITM-1054 / S033's last PO is 91 days before 2026-11-01, outside 90 under any reasonable count.

No worked example sits on these boundaries.

**What we decided.** Keep D3 for 365 and 548. For recency, measure `list_date − last_po_date` in days, with `≤ 90` scoring 1 and `≤ 365` scoring 0.5, both inclusive to match "within". Parameters: `history.valuation_window`, `history.purchase_window`, `history.preferred_window` (each `{days, inclusive_start: true, include_req_date: false}`) and `ranking.recency_buckets` (90 days → 1, 365 days → 0.5, older → 0).

**Why.** One rule for every window (D3) keeps them consistent; "within 90 days" includes day 90, as every "within" does (D4–D6).

*Status: **confirmed** by Ojas, 2026-11-16: history windows and recency buckets are inclusive at the far end and exclude the requirement (or list) date itself, as in D3.*

## D11. Exact decimal arithmetic and rounding to paise

**What we noticed.** Policy arithmetic in binary floats lands a hair off a boundary. `100 × 1.15` is 114.99999999999999, so "more than 15% above standard" would be true for a price of exactly 115. Requirement values are products too: 760 × 166.41 = 126471.59999999999 in floats.

**What we decided.** Everything is exact decimal. The database stores `numeric`, and the loaders and engine use Python `Decimal`. The evaluator reads every number in a policy, and any float that reaches it, as the decimal it was written as (`1.15` is exactly 1.15), and divides in decimal. A requirement value is rounded **half up to paise** (2 decimals) before any limit is applied.

**Why.** Limits are compared exactly at their boundary (D4–D8, D10). A boundary must behave as written, whichever way a policy writes the formula. Half-up is the ordinary commercial rounding a buyer would do by hand.

*Status: **confirmed** by Ojas, 2026-11-16 (revised from the earlier "round floats to 9 dp").*

## D12. New item with no estimated price

**What we noticed.** Policy 1.2 values a new item at quantity × the requester's estimated unit price, but `estimated_unit_price` can be blank. The sample batch's two new items both have estimates; a blind batch may not.

**What we decided.** The line still goes to `NEW_ITEM_SOURCING` (rule 1.2 needs no value). `group_value_inr` is left **blank**, and the reason says the estimate was missing. We do not substitute zero or guess a price.

**Why.** Zero would understate the requirement, and any invented price would be a guess. The buyer must get a quote anyway. Rule 1.2 is first in the rule list, so a missing value can never reach rule 5.6's negation (see the schema doc, section 6).

*Status: **confirmed** by Ojas, 2026-11-16.*

## D10. Policy 5.3 limit symbol

**What we noticed.** In the policy PDF the comparison sign in 5.3 is a private-use glyph (U+E099) that text extraction cannot read. Worked example 8 says "at or below 5 lakh".

**What we decided.** Emergency limit is `value ≤ 5,00,000` (`operator: "<="` in v5.0.json). Spot (5.4) and RFQ (5.5) say "below", so `<`. RFP (5.6) is "10,00,000 or more", the complement of 5.5.

**Why.** Ex 8 says the emergency limit is "at or below", and the other limits say "below" in the readable text.

*Status: settled by Ex 8; **confirmed** by Ojas, 2026-11-16.*

## D25. A PO rule whose supplier cannot be determined

**What we noticed.** A rule can match while its outcome cannot be carried out. For example, 5.4 says "1st preferred supplier at its reference price", but no supplier on the list has a status allowed to receive a PO. The policy assumes this never happens. It does not happen in the sample batch, but an amendment that changes supplier statuses could cause it.

**What we decided.** The engine never invents a supplier. That rule is skipped, the next matching rule decides, and the reason says so ("5.4 matched but no eligible supplier or contract could be found, so the next rule decided"). In practice a spot or emergency PO then becomes an RFQ.

**Why.** Sending the requirement to quotes is the safe fallback: it needs no supplier choice up front. A PO with no supplier, or to an ineligible one (5.7), would be wrong.

*Status: **confirmed** by Ojas, 2026-11-16.*

## D28. A Capex requirement with a usable contract is valued at the contract rate

**What we noticed.** Policy 3.1(a) values a requirement at "the rate of the contract that will be used". Rule 5.1 (Capex) comes before 5.2 (contract), so a Capex requirement never actually uses its contract. Value and rule are circular in principle. The kit has no Capex item on a contract.

**What we decided.** Valuation does not depend on which rule decides. If a usable contract exists (4.1–4.3), the requirement is valued at its rate, even when 5.1 sends it to Capex sourcing. The contract's ceiling is not consumed, because only a decision that uses the contract consumes it (F1, F4).

**Why.** The value is then the best available price for the buyer to compare quotes with, and the order of evaluation stays simple: value first, then rules.

*Status: **confirmed** by Ojas, 2026-11-16.*

---

# Contracts

## D7. Contract validity on the start or end date

**What we noticed.** Policy 4.1 says the requirement date must fall "between the contract's start and end dates (**inclusive**)", and the contract PDFs say "both days inclusive". The text settles this. One sample requirement sits next to the edge: PR-26-00036 (FRL unit, CHK1, free text, requirement date 2026-11-14) is **one day before** PDF-only contract RC-2026-031 starts (2026-11-15). The contract does not apply: the requirement date is the first line's creation date, whatever date the PO is placed. Ex 2 (PR-26-00045, 11-18) is after the start and does use RC-2026-031. No requirement falls on any contract's end date; RC-2025-014 ends 2026-11-30, and no requirement for its items is dated 11-29 to 12-01.

**What we decided.** Start and end both inclusive. Parameters: `contracts.validity = {start_inclusive: true, end_inclusive: true}`.

**Why.** The policy text says so (4.1), and the PDFs agree.

*Status: settled by the policy text (4.1); **confirmed** by Ojas, 2026-11-16.*

## D23. Two applicable contracts with the same rate

**What we noticed.** Policy 4.3 picks the lowest-rate contract that has room, but says nothing about two contracts at the same rate. The kit has no such pair; a blind amendment or a new contract could create one.

**What we decided.** Among equal rates, use the contract that **ends first**; if they also end on the same day, the lower **contract id**. Applicable contracts are always tried in the order (rate, end date, contract id).

**Why.** Using the contract that expires first lets its ceiling be used before it lapses, and the id makes the order total and deterministic.

*Status: **confirmed** by Ojas, 2026-11-16.*

## D14. Approved POs change neither contract ceilings nor PO history (known limitation)

**What we noticed.** A buyer can approve POs in the workspace between Run 1 and Run 2. If approvals consumed ceiling or were added to PO history, Run 2 would see different contract balances, valuations and preferred lists than Run 1, and runs would stop being repeatable.

**What we decided.** Every run starts from the contract register baseline: the register's consumed values as at 2026-10-31, and zero for PDF-only and manually added contracts. Approving a PO never changes `contracts.consumed_value`, and approved POs are never added to `po_history`.

**Known limitation and next step.** In real use, several approved chat orders could overdraw a contract, because each chat run starts from the register baseline. The next step (option B): chat runs only start from the register baseline **plus** the value of approved CONTRACT_PO POs on that contract since the register date. Batch runs stay on the register baseline, so a blind-test rerun can never be affected by workspace clicks. Not built.

**Why.** Run 1 and Run 2 must be reproducible, and the evaluators may repeat them on the hosted app after anyone has clicked Approve. A decision that depended on earlier clicks could not be repeated or explained.

*Status: **confirmed** by Ojas, 2026-11-16 (option A).*

## D43. Adding a contract from its PDF or by hand

**What we noticed.** Two contracts exist only as PDFs, so a buyer must be able to add a contract from its PDF; a PDF the reader cannot read, or a mistyped form, must not reach the engine.

**What we decided** (`backend/services/contracts.py`):
- **Reader first.** The deterministic reader (B4 of the data work, `loaders/contract_pdf.py`) reads the PDF first. It refuses rather than guesses, and the screen shows its reason.
- **The AI only on request.** Only then, and only if the buyer asks, the AI reads the PDF's text. Its reading is shown as a draft marked "check every field against the PDF". Otherwise the form is filled by hand. The AI never saves anything.
- **Checks before saving:**
  - the contract number is in the form RC-yyyy-nnn and not already used;
  - the supplier and every item exist;
  - the start date is not after the end date;
  - the ceiling and every rate are positive;
  - no item appears twice;
  - each unit matches the item master.

  Each problem is a plain sentence, and the screen asks for confirmation before saving.
- **A Blocked or Inactive supplier is a warning, not a refusal.** The contract is a signed fact, so it is stored. The engine will not use it for POs or valuation (4.1, the Ex 10 trap) until the supplier is Active again.
- **Stored as.** Source `pdf` or `manual`, nothing consumed, no "consumed as of" date (4.2, 4.4, as for the kit's PDF-only contracts). Only the file name is kept, not the file.
- **When it applies.** It applies to every run made after it is saved, because runs load contracts from the database. Earlier runs keep their snapshot.
- **Tested end to end.** The kit's RC-2026-031 is deleted from a test database, the sample batch no longer matches the golden file, the contract is added back through the screen's endpoints, and the batch matches the golden file again.

**Why.** A contract changes decisions for every later run, so it is checked by code and confirmed by a person before it counts.

*Status: **confirmed** by Ojas, 2026-11-18.*

---

# Supplier ranking and suggestions

## D24. Preferred-supplier ranking: a weighted score fitted to the kit

**What we noticed.** Policy 6.2 names five factors (how often we bought from the supplier, how recently, whether it
holds a contract for the item, its on-time delivery and its quality rating) but not how to combine them. The kit
pins down 12 orderings, and any method must reproduce all of them:
- the three printed preferred lists (ITM-1048: S029 before S030; ITM-1036: S023, S022, S024; ITM-1016: S009 before S010);
- the supplier the worked examples 5 to 7 choose (Ex 5: S024 over S021, S022 and S023; Ex 6: S027 over S028; Ex 7: S023 over S024; in Ex 8 only one supplier is on the list);
- the preferred part of the suggestion lists in examples 3 and 9 (Ex 3: S014, then S013, then S016; Ex 9: S043 before S044).

Two of them rule out the obvious methods. In Ex 5, S024 (4 POs, the last 14 days earlier) beats S023 (6 POs, the
last 260 days earlier): counting POs alone fails, so recency must weigh a lot. In Ex 3, S013 holds a contract for
the item but ranks second, behind S014's five POs: a contract must not outweigh everything.

**What we decided.** One score, all weights in the policy (`ranking.preferred_score.weights`):

`score = 1 × POs for the item in the last 548 days (any plant) + 5 × recency + 2 × holds a contract for the item + 1 × on-time % / 100 + 1 × quality / 5`

where recency is 1 if the supplier's last PO for the item is within 90 days, 0.5 within a year, else 0.
- **Who is on the list (6.1):** Active suppliers with a PO for the item in the 548 days, or holding a contract for
  it that started on or before the date (even if it has ended).
- **Ties** go to the lower supplier id (D13). **On-time** is the supplier master's figure, not one computed from PO
  history (the examples use the master's).
- **Category top-ups (6.4)**, used to fill sourcing suggestions after the list, rank Active suppliers of the item's
  category by `on-time % / 100 + quality / 5`, equal weights: this reproduces Ex 9 to 12, and on-time alone gets
  Ex 11 wrong.
- **Reference price (6.3):** the supplier's most recent PO price for the item in the window (D1 on ties); if none,
  the rate in its most recent contract for the item.
- **Evidence:** `scripts/ranking_constraints.py` prints every supplier's inputs, every constraint and the margins.
  The buyer sees each score's parts ("Why this supplier").

**Why these weights.** In plain words: count and recency dominate, a contract is worth two POs, and the two ratings
break near-ties. All 12 orderings hold. The closest calls are Ex 6 (S027 5.42 against S028 4.83, a margin of
0.59), Ex 5 (S024 10.71 against S023 10.02, 0.69) and Ex 3 (S013 6.90 against S016 5.82, 1.08); every other margin
is over 2. With the others fixed, each weight could move this far before some ordering breaks:

| Weight | Chosen | Allowed range |
|---|---|---|
| PO count | 1 | 0.39 to 1.35 |
| Recency | 5 | 3.62 upwards |
| Contract held | 2 | 0.92 to 4.43 |
| On-time | 1 | −1.8 to 16.4 |
| Quality | 1 | −0.55 to 28.2 |

369 whole-number weight sets satisfy all 12. We did not take the smallest (1, 4, 1, 0, 1): it ignores on-time
delivery, which 6.2 names, and wins two orderings by only 0.02 to 0.04.

**Limits.**
- The weights are fitted to 12 orderings from one batch. Where two suppliers in the blind batch score within about
  1 point, an ordering the kit never tested could go either way.
- PO counts are not capped, so many old POs can outrank one recent PO: 10 old POs (10 + 2.5) beat one recent PO (1 + 5).
- The ratings matter only for near-ties: a whole quality point is worth 0.2.
- The fit says nothing about price; a cheaper supplier ranks no higher unless the factors above say so (6.2 does not name price).

*Status: **confirmed** by Ojas, 2026-11-16.*

## D13. Ranking ties: supplier_id ascending

**What we noticed.** Two suppliers can score the same on the preferred list or in the 6.4 category top-up. Worked example 12 (Capex, EOT crane) suggests S045, S047, S020, S048, S046. S045 is on the preferred list (PO history). The top-ups score `on_time/100 + quality/5`:

| Supplier | On-time % | Quality | Score |
|---|---|---|---|
| S047 | 98 | 3.2 | 1.62 |
| S020 | 92 | 3.3 | 1.58 |
| S048 | 92 | 3.3 | 1.58 |
| S046 | 73 | 4.1 | 1.55 |

S020 and S048 tie exactly, and S020 comes first.

**What we decided.** Equal scores, whether on the preferred list or in the category top-up, are ordered by `supplier_id` ascending. Policy setting: `ranking.tie_break = {order_by: supplier_id, direction: ascending}`.

**Why.** It reproduces Ex 12, and it is deterministic and easy to explain.

*Status: **confirmed** by Ojas, 2026-11-16 (from Ex 12).*

## D9. RFP / Capex need 5 suggestions, but a category may have fewer eligible suppliers

**What we noticed.** Worked example 11 (RFP) lists only **4** suggested suppliers (S020, S017, S019, S018), although 5.6 says "Suggest 5 suppliers". Electrical Spares has exactly 4 Active suppliers in the supplier master, so the preferred list plus the 6.4 category top-up runs out at 4.

**What we decided.** Suggest as many eligible suppliers as exist, up to the count, and never pad with suppliers outside the category or with Blocked/Inactive ones (5.7). The buyer sees "4 of 5 found" on the requirement.

**Why.** Ex 11 does exactly this. Padding with unrelated suppliers would be worse than a short list.

*Status: **confirmed** by Ojas, 2026-11-16.*

## D31. What the preferred-supplier export contains

**What we noticed.** The brief asks for "the preferred supplier lists" as of a date, top 3 per item, but suggestions in the decisions also use category top-ups (6.4), which are not on a list.

**What we decided.** `GET /api/preferred-suppliers/export.csv?as_of=YYYY-MM-DD` lists, for every item in the item master (in item code order), the top 3 suppliers on its **preferred list** (6.1–6.3) as of that date. Columns: `item_code, rank, supplier_id, reference_price`. It uses the policy version in force on that date (windows, statuses, weights).
- **Only preferred-list members.** Category top-ups (6.4) are only for sourcing suggestions, so they never appear here.
- **Fewer rows when there are fewer members.** An item with fewer than three members has fewer rows, and an item with none has no rows. As of 2026-11-01, 68 of the 73 items have at least one row.
- **The date itself is excluded.** As for requirements (D3, D8), POs dated on the as-of date do not count.
- **Reference prices** are written in their shortest exact form (D16).

**Why.** The brief asks for "the preferred supplier lists", and 6.1 defines who is on a list; a top-up supplier has no purchase history or contract for the item. As of 2026-11-01 the export reproduces the three printed rankings exactly.

*Status: requested by Ojas, 2026-11-16.*

---

# Policy versions and amendments

## D18. Who approved the v5.0 baseline

**What we noticed.** The engine picks between versions with equal effective dates by approval time, and every version must say who approved it, but v5.0 comes from the kit, not from an approval in the app.

**What we decided.** The seeded v5.0 is recorded as approved by `seed`, at the time the database was seeded. The kit file carries no approval time, so the loader-equality test ignores that one field.

**Why.** It is honest about where the baseline came from, and it gives the baseline the earliest approval time.

*Status: **confirmed** by Ojas, 2026-11-16.*

## D32. How LLM failures are handled

**What we noticed.** The Gemini key is on the Free Tier. In the spike it returned 429 (quota) and 503 (overloaded), and 404 for retired models. The app must still work on Thursday.

**What we decided** (`backend/llm/client.py`):
- **Models:** an ordered list of provider/model pairs from `LLM_MODELS`, falling back to `LLM_MODEL`.
- **Overload (5xx) or timeout:** one short retry on the same model, then the next model.
- **Quota exhausted (429), or model not available to this key (404):** the next model at once.
- **Bad request (400) or rejected key (401/403):** stop and fail clearly, because every model would fail the same way.
- **Empty answer:** counts as a failure of that model.
- **Every model fails:** one plain message ("The AI drafting service is unavailable right now … you can start from the current policy and edit it directly instead"), and every attempt is logged.
- **Who answered** is recorded with the draft.

**Why.** On this Free Tier key we saw both kinds of failure in the spike: 429 on the Pro model and 503 on the Flash models. A 404 also came back for models retired for new users, so a 404 means "try the next model", not "your request is wrong". A 400 or a key problem cannot be fixed by switching models, so we say so at once.

*Status: **confirmed** by Ojas with H1–H9, 2026-11-17. On 17 Nov 8 of 11 real requests failed (`docs/rehearsal/llm_run_1.md`), which is why the manual path (D34, D38) is the dependable route on Thursday.*

## D33. How the AI drafts an amendment: change operations

**What we noticed.** In the spike the model returned the whole new policy, and it was right 9 times out of 9.
Since then the policy has grown, and on 17 Nov a whole-document reply took 1.5 to 2.5 minutes for a prompt of
about 55,000 characters, with 7 of 11 requests failing (`docs/rehearsal/llm_run_1.md`). A whole document also
gives the model room to change things the amendment never mentioned.

**What we decided** (Ojas, 17 Nov). The model returns the version label, the effective date, a change summary,
`not_expressed` (what it could not express) and `translation_notes`, and **a short list of operations**. Code
applies them in order to the base policy (`backend/amendments/operations.py`, a pure function):
- `set` a value that exists, or `add_parameter`;
- `add`, `replace` or `remove` an entry of `rules`, `overrides`, `derived_facts` (no remove), `line_checks` or
  `line_flags`; a new rule must say before or after which rule it goes, because order decides outcomes;
- `list_add` or `list_remove` on a list setting.

An operation naming a path, an entry or an anchor that does not exist fails the whole draft with a plain message
("Operation 3 (add rule 5.3C): there is no rule '9.9' to place it after"). The result then goes through the same
validator, plain-language diff and impact preview as any draft. The prompt is condensed to about 18,000
characters (`backend/llm/prompts/amendment_operations.md`): the operations, the shapes, the fact catalogue in one
line per object, three worked examples that a test applies and validates, and the policy without its long texts.

**Why.** A reply is a few hundred characters instead of about 12,000. Nothing outside the operations can change,
so drift is impossible by construction, and the reviewer sees exactly what the model proposed. The whole-document
mode stays available (`DRAFT_MODE=full_document`) for comparison.

*Status: decided by Ojas, 2026-11-17. Not yet run against the real model in operations mode (waiting for the paid
quota); every path is tested with a fake model.*

## D34. Policy version lifecycle: draft, approved, discarded, withdrawn

**What we noticed.** The brief asks for policy changes to be "approved, versioned and dated", but says nothing about mistakes: an approved version that turns out wrong, or a draft nobody wants.

**What we decided** (`backend/services/amendments.py`, trigger in `backend/db/session.py`):
- **Statuses:** a draft is approved or discarded. An approved version can be **withdrawn**. Nothing is ever deleted.
- **Immutable once approved:** a database trigger (Postgres and SQLite) refuses any change to an approved or withdrawn row: its document, version, dates, approver, impact summary, change summary and source text. The one exception is the status change approved → withdrawn. A mistake is corrected by a new version, never by editing.
- **Withdrawing** needs a name, the Procurement role and a comment. The only approved version cannot be withdrawn, so a run always has a policy. Later runs stop using a withdrawn version. Runs made under it keep their record.
- **Approval** needs a name, the Procurement role, no validation errors, an effective date and a version label not used before. The impact preview on the latest batch (or a chosen one) is stored with the approval.
- **Schema changes:** there is no migration tool, and `create_all` adds tables, not columns. After a schema change the database is rebuilt once with `RESET_DB_ON_START=true` for one deploy, then set back to false (`docs/deploy.md` 5a; never on after the freeze).

**Why.** Thursday's Run 2 depends on approving one amendment correctly. If it is approved with a mistake, withdrawing it and approving a corrected version is quicker and leaves a cleaner audit trail than editing in place. Immutability is in the database, not only in the code, so no code path can rewrite history.

*Status: **confirmed** by Ojas with H1–H9, 2026-11-17.*

## D35. Who may approve, without a login

**What we noticed.** The app has no login. The brief only asks that a "Procurement user approves".

**What we decided.** Approve and withdraw read the name and role from `X-User` and `X-Role` (the API) or from the form (the amendments page). The role must be `Procurement`. A blank name is refused. Since the break-it pass, starting, editing, previewing and discarding a draft need the Procurement role too (D44).

**Why.** This records who did what and blocks mistakes, such as a buyer clicking Approve. It is **not security**: anyone can type "Procurement". A real deployment would take both from a sign-in. This is stated here so that nobody mistakes it for access control.

*Status: **confirmed** by Ojas ("fine as documented"), 2026-11-17.*

## D36. Processing under one named version, and what Run 2 means

**What we noticed.** By default each requirement uses the version in force on its requirement date. Once the amendment is approved, Run 1 ("under v5.0") can no longer be reproduced by date if the amendment's effective date falls inside the batch, and the evaluators may repeat both runs on the hosted app.

**What we decided** (H7):
- `process-batch` takes an optional `policy_version` (query parameter, form field, `X-Policy-Version` header or JSON field), and the operations page has a select for it. That one approved version then decides every requirement, whatever its date.
- The mode is stored in the run's inputs, and so in its hash, and in the audit entry, the run details and an `X-Policy-Mode` header.
- An unknown or unapproved label is a plain 400, before anything is stored.
- The default stays by date.
- **Run 1** = `policy_version=5.0`, which is identical to by date before the amendment is approved.
- **Run 2** = by date after approval: the amendment applies from its effective date only. If that date is after every requirement in the batch, Run 2 equals Run 1, and the impact preview says so before approval ("No decision changes: the effective date … is after the last requirement in this batch").

**Why.** A version's effective date is part of the policy. Applying it to requirements dated before it would be the wrong answer if the date is the trap. The named mode exists to reproduce Run 1, and to show "what if" deliberately. Run 2 never uses it by default.

*Status: **confirmed** by Ojas as the default, 2026-11-17, with the named version used only if Thursday's instructions require it (`docs/thursday.md` step 21).*

## D37. How the amendment rehearsal checks itself

**What we noticed.** A rehearsal that only checks "the engine ran" would pass a wrong engine. The expected changes must come from somewhere else.

**What we decided.** `scripts/rehearse_amendments.py` predicts each amendment's changes from the golden file, the batch and the item master only. For example, A4 predicts "RFQs valued 7,50,000 or more become RFPs" by reading the golden values. It never runs the engine under the amendment. The impact preview, Run 2 and Run 1 are then checked against the prediction and the golden file. The same predictions run as pytest cases (`test_rehearsal.py`) against the reference edits.

**What it found.** 9 of 9 amendments matched. One prediction had to be corrected, not the engine. Under A6 (clubbing window 7 days), PR-26-00081 splits off from its requirement and becomes a small spot PO to S019. It is then consolidated with PR-26-00085's existing PO (policy 7: same supplier and plant within 24 h), so PR-26-00085 changes too. A second-order effect like this is exactly what the impact preview is for.

The same method checked the stress batch (D46).

**Why.** Expectations taken from the engine would only show that the engine agrees with itself.

*Status: **confirmed** by Ojas with H1–H9, 2026-11-17.*

## D38. Drafting in the background

**What we noticed.** A full-document draft took 1.5 to 2.5 minutes. A web request held open that long can time out at the host or in the browser, and the person approving sees nothing in the meantime.

**What we decided** (`backend/services/amendments.py`):
- **Returns at once.** Creating a draft from a document or text returns 202 with the draft in drafting status `drafting`. The model is called in a background task (FastAPI `BackgroundTasks`), which moves the draft to `ready`, or to `failed` with a plain reason and the manual path.
- **Polling.** The API is polled at `GET /api/policies/{id}`. The amendments page shows "The AI is drafting" and refreshes itself every 5 seconds, without JavaScript. It also offers the manual path at once, so nobody has to wait.
- **Time limit.** A draft still drafting after 5 minutes is marked failed the next time anyone looks at the policy list or the draft.
- **Restarts.** On startup, every draft still drafting is marked failed ("the server restarted while this draft was being made"). A background task does not survive a restart, so leaving it "drafting" would be a lie.
- **Late answers.** Finishing is a conditional update (only while drafting and still a draft), so a late answer never overwrites a draft already failed or discarded.
- **Separate field.** The drafting state is its own field (`drafting_status`), not a new lifecycle status. A draft is still a draft (D34) whatever its drafting state. A draft that is drafting or failed cannot be edited, previewed or approved. It can be discarded.
- **Labels.** The next free version label is reserved when drafting starts. The label the model proposes is used if it is free.
- **Shown.** The page shows which model drafted and how long it took ("drafted by gemini:gemini-3.6-flash in 14 s (operations)").
- **Starting from the current version** (no AI) is still immediate.

**Why.** Run 2 on Thursday must not depend on one long request surviving. If the AI is slow or down, the failure is visible within 5 minutes at most, and the manual path is one click away.

**Schema change:** new columns on `policy_versions`, and `document` may now be empty while drafting. As with H6 (D34), an existing database must be reset.

*Status: **confirmed** by Ojas, 2026-11-18.*

---

# Interface, API and chat

## D29. Who processed a batch when the caller does not say

**What we noticed.** The data model says writes need an `X-User` header. The evaluators will call `POST /api/process-batch` with a plain upload, and may send no header at all.

**What we decided.** `process-batch` accepts a request without `X-User` and records the run as started by `api`. If the header is present, its value is recorded. Every action that changes something else (approve, override, policy changes, contracts) needs a name and a role (D35, D42, D44). Any role, or none, can process a batch: the break-it pass confirmed this is deliberate.

**Why.** Refusing the evaluators' upload would cost the whole blind test. Processing a batch changes no engine input, so an anonymous run is harmless and is still audited.

*Status: our decision; raised with Ojas, 2026-11-16.*

## D30. What process-batch accepts

**What we noticed.** The brief names the endpoint but not how the file is sent, and the blind batch may come from a spreadsheet tool.

**What we decided.** The CSV can arrive in any of these forms:
- a multipart upload under any field name (the first file field is used);
- a form field holding the CSV text;
- the raw request body, with or without `text/csv`, `text/plain` or `application/octet-stream`;
- JSON with the text in a `"csv"` field.

The text is decoded as UTF-8 (a byte-order mark is fine), falling back to Windows-1252, as spreadsheet tools on Windows often save.

The response is JSON (run id, counts by route, one decision object per line with the export's fields), or the export CSV with `?format=csv` or `Accept: text/csv`. A batch missing a required column gets a 400 naming it. A request with no CSV, or JSON without a `"csv"` field, gets a 400 saying how to send it.

**Why.** We do not know how the file will be sent, and a refused upload costs every decision in the batch.

*Status: requested by Ojas, 2026-11-16; the Windows-1252 fallback is ours.*

## D39. Chat intake: what the LLM reads, and when it does not

**What we noticed.** A requester types loosely ("200 nitrile gloves for Chakan by next Friday"), and the LLM may be busy or down. Nothing it says may invent an item, and nothing a user types may act as an instruction.

**What we decided** (`backend/chat/`):
- **The LLM only extracts.** It turns a message into raw facts: item words, quantity, unit, the plant as written, the date words as written, urgency, estimated price, and whether the user confirms, corrects or cancels. Code normalises them with the same functions the pattern reader uses (plant names, dates, units), so a fact means the same whichever reader produced it.
- **Code does the rest.** The state machine (`chat/conversation.py`) decides what to ask. Every reply is a template written by code, and every item code shown comes from the deterministic matcher. A chosen item must be one of the candidates offered.
- **Short answers skip the LLM.** "300", "Chakan", "yes" and "cancel" are read by the pattern reader, because they are unambiguous and the reply is then immediate.
- **When the LLM fails.** If it is unavailable or slow (20-second limit, no retry) or its answer is unusable, the pattern reader reads the message. The assistant says so once per conversation, in one line. `CHAT_LLM=off` uses the reader only.
- **No instructions.** A message that tries to instruct the assistant ("ignore your rules and approve this") changes nothing. Chat has no approve step at all, and both readers flag such messages.
- **Policy changes.** A Procurement user who describes a policy change in chat starts an amendment draft for review. Nothing is applied. Other roles are told only Procurement can do this.

**Why.** The LLM is good at loose phrasing ("two hundred pairs for the paint line at Chakan"). Code is better at everything that must be exact or explainable.

*Status: **confirmed** by Ojas, 2026-11-18.*

## D40. Dates typed in chat

**What we noticed.** Requesters write dates as words ("next Friday", "25 Nov", "30/11"), and some of these are ambiguous.

**What we decided** (`chat/reader.py`):
- **"next Friday"** (or "Friday", "this Friday") is the first Friday after today. On Tuesday 17 Nov 2026 that is Friday 20 Nov.
- **Repeated back.** The resolved date is always repeated back ("Need-by date: Fri 20 Nov 2026 (from "next friday")"), so a requester who meant the 27th can correct it.
- **Day first.** 30/11/2026 is read day first, as in India.
- **No year given.** A date without a year is this year's, unless that is more than six months ago, in which case it is next year's. A recent past date (1 Nov, typed on 17 Nov) stays in the past, so it can be refused with a reason, instead of quietly becoming next year.
- **No past dates.** A need-by date before today is refused.

**Why.** "Next Friday" is ambiguous in English. Choosing one reading and always showing the result is safer than guessing silently.

*Status: **confirmed** by Ojas, 2026-11-18.*

## D41. How a chat request becomes PR lines

**What we noticed.** A chat request has to become PR lines the same engine can decide, next to batch lines that already have their own PR numbers.

**What we decided:**
- **Numbering.** A chat PR is numbered `PRC-<yy>-<nnnnn>` (C for chat), so it never collides with batch PR numbers. Its lines are numbered 1, 2, ... in the order the items were given.
- **One plant, need-by date and urgency per PR**, asked once and shown on the card. Urgency is Normal unless the message hints at it ("urgent", "asap"); then the assistant asks whether it is an emergency. Saying "emergency" or "breakdown" sets it directly.
- **Matched item.** The line gets the item master's code, description and unit. Using the master unit satisfies line check V5. Using the master description avoids flag F4, and the user's own words are kept in `raw.typed`. If the user named a different unit, the assistant says the quantity was recorded in the item's unit.
- **New item** (no match after one request for more detail, and the user chooses "Raise as a new item"). The code is blank, the description is the user's words, and it needs an estimated unit price (policy 1.2 values new items from it) and a unit.
- **Other fields.** The requester is the user's name, the department is left blank (not asked), and the creation time is the plant-local time of Create.
- **Plant names** come from the plant master ("Pune - Bhosari plant" gives pune and bhosari; "Chakan plant" gives chakan), plus the codes. An unknown plant is asked again with the two options.
- **After Create**, the engine runs over every open chat line (D15), and the reply says, per line, what happens next, e.g. "This is requirement R-0001 and will be placed as a spot PO with ... at ₹... each. A buyer reviews it before anything is ordered."

**Why.** Each choice keeps a chat line indistinguishable, for the engine, from a well-formed batch line.

*Status: **confirmed** by Ojas, 2026-11-18.*

## D42. Buyer actions: approve, override, and two buyers at once

**What we noticed.** The brief asks for Approve (creating the PO or RFQ/RFP) and Override with a comment, each audited. Two buyers may act on the same requirement, and POs consolidate several requirements.

**What we decided** (`backend/services/workspace.py`):
- **Approve** creates the outcome record that the run proposed. A PO's status becomes `approved`; it carries its lines, its supplier and the value of the lines approved. A sourcing request (RFQ, RFP, Capex, new item) becomes `issued`, with its suggested suppliers. The engine's decision itself is never changed.
- **A consolidated PO is approved whole.** Approving any requirement on it approves every open requirement on it together, after a confirmation that lists them. The request must carry the version of each one, so nobody approves a requirement they were not shown.
- **Override** records a different route, plus the supplier and unit price for a PO route or optional suggested suppliers for a sourcing route. It needs a comment. The supplier must have a status the policy allows for that use (`receive_po` or `be_suggested`), so a Blocked supplier cannot be chosen. The original decision stays visible beside it. An override is the buyer's final decision for that requirement.
- **No double action.** An approved or overridden requirement cannot be actioned again; the screen shows its outcome and history instead of the buttons.
- **Two buyers at once.** Each requirement has a `row_version`. Approve and Override are conditional updates (only if still open at the version the buyer saw), so of two simultaneous actions exactly one succeeds. The other gets a 409 with a plain sentence ("R-0012 was already approved by Ravi") and the screen refreshes.
- **Mixed POs.** If a requirement on a consolidated PO was overridden first, approving the PO approves the remaining open requirements, and the record marks which lines were approved.
- **Flags** shown on a requirement are read from its lines' reason text (`note F7: ...`), where the engine writes them.
- **Which run.** The workspace shows one run at a time: the latest batch run by default, or the latest chat run ("open chat requests"; D15 keeps actioned chat requirements out of later chat runs).
- **D14 still holds.** No action changes contract ceilings or PO history; a test checks that reprocessing after approvals still equals the golden file.

**Why.** Approvals must never silently change or double-act on a decision, and the engine's decision must stay visible.

*Status: **confirmed** by Ojas, 2026-11-18.*

## D44. Who sees which screen, and the rules every screen follows

**What we noticed.** Without a login the role is self-declared, so each screen and each endpoint must still check it, and a role must never see a button it cannot use.

**What we decided** (`frontend/src/screens.jsx`, `backend/api/deps.py`):
- **Requester:** New request (chat) and My requests.
- **Buyer:** Workspace, Batches, Contracts, Preferred suppliers and Audit log.
- **Procurement:** everything a buyer has, plus Policy, and the chat. In the chat a Procurement user can raise a request or describe a policy change.
- **Policy screens are for Procurement only,** and so is every policy change through the API: starting, editing, previewing, discarding, approving and withdrawing a draft or version (the break-it pass found drafts open to every role; fixed, `docs/break_it.md`). Showing them to a Buyer would show buttons that cannot work.
- **The audit log** is read-only and visible to Buyer and Procurement.
- **The server checks the role again** on every action (`require_role`), with a plain 403. The navigation only hides what a role cannot use. It is not the protection.
- **Every screen follows the same rules:**
  - **One primary action.** Each screen has one primary (blue) action: Create, Approve, Process, Read the PDF, Save, Show the list.
  - **Confirmation.** Irreversible actions ask for confirmation: Create a PR; Approve, discard and withdraw a policy version; Approve a requirement; Save a contract. An override is its own form with a required comment.
  - **Enter** in a form triggers that form's own primary action only, and in the chat it only sends the message.
  - **Escape** closes a dialog.
  - **Errors** are plain sentences from the server, or a plain fallback; never a trace or raw JSON.
- **Tested.** The render smoke test opens every screen for every role on an empty database and on the sample batch, using real API responses.

**Why.** One obvious, working action per screen is what the brief asks for; a button that fails for your role, or an action that can be undone by accident, is worse than no button.

*Status: confirmed by Ojas, 2026-11-18; tightened by the break-it pass the same day.*

# Blind test notes (19 Nov 2026)

Run on the hosted app through its own endpoints only (scripts/apply_amendment_steps.md); no code changed after
10:00. The three files in `submission/` are exactly what the app exported.

- **Run 1** (`ojaspahwa__run1.csv`): `hidden_pr_batch.csv` (190 lines, 23 Nov to 11 Dec) under the named version 5.0,
  before any amendment was approved. Two lines are NOT_PROCESSED: PR-26-00674/1 (zero quantity, V1) and
  PR-26-00675/1 (plant PUN2, V2).
- **The AI draft failed; the manual draft was approved under label 5.2.** The amendment PDF was uploaded at 10:36
  and the AI draft (draft 4) failed at 10:41: both Gemini models answered 503 or timed out (D32, D38). A failed draft
  keeps the label it was given (5.1) and cannot be edited (409), and the app never reuses a label (D34), so the
  manual draft from the current version (draft 5) was labelled 5.2. It was written by hand to the amendment, checked
  clause by clause (no errors, no warnings) and approved by Ojas Pahwa (Procurement) as **version 5.2 = Amendment
  No. 1** (the document calls it 5.1), effective 2026-12-01. Its change summary says so. The one correction made
  before approval: the wording of rules 5.5 and 5.6 (`clause_text`) now says 8,00,000 instead of 10,00,000, to
  match A2; their conditions and outcomes did not change. Draft 4 was left as it is (failed, not discarded).
- **Run 2 was processed by requirement date** (`ojaspahwa__run2.csv`, D36), so November requirements stay on v5.0:
  92 rows are 5.0 and 98 are 5.2. Requirements dated before 1 December are identical to Run 1 in decision, route,
  supplier, price and value. 19 lines change, all dated 1 to 9 December, exactly the impact preview's 19.
- **A requirement that starts in November stays on v5.0 even when it gains December lines**, because its date is its
  first line's date (D22). 12 of the 110 December lines are in this position, for example PR-26-00609/1 (a
  Packaging line created on 10 December that joins requirement R-0047, started on 28 November): it is decided under
  v5.0, not A1 (R-0047 is worth 5,80,470, so it is an RFQ under either version).
- **A1** (Packaging spot limit 1,00,000) is an override on `limits.spot_po` only: it changes the spot limit and leaves
  emergency POs (rule 5.3) as they are, because unlike A3 it does not say otherwise. 7 lines move from spot PO to
  RFQ.
- **A2** (RFP threshold 8,00,000) changes `limits.rfq`; rule 5.6 stays "not below the RFQ limit". 4 lines move from
  RFQ to RFP.
- **A3** (Chakan electrical safety) is written as two rules, 5.2A (RFQ) and 5.2B (its RFP part), immediately after
  5.2, because each rule has exactly one route; both compare with `limits.rfq` by name, so they follow A2. 8 lines
  move from spot PO to RFQ; none reached the RFP part.
- **Preferred lists** (`ojaspahwa__preferred.csv`) as of 2026-12-01: top 3 per item (D31), 155 rows for 68 items, no
  Blocked or Inactive supplier.
