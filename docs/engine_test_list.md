# Engine and app test list

Status last updated after F6 (the whole engine), 2026-11-16. Rows 36–45 are app tests, not built yet.

Cases found during the spike, kept here so they are not lost before the engine exists. Each becomes at least one pytest case. "Ex n" = Worked_Examples.pdf; "D n" = DECISIONS.md. Values are INR.

The matcher in `scripts/data_questions.py` is throwaway. The engine must not import it. The real matcher gets its own tests.

## Worked decisions (ground truth)

| # | Case | Expected | Status (after F6) |
|---|---|---|---|
| 1 | Ex 1: PR-26-00019/1, PUN1, ITM-1002, 15 NOS, 2026-11-04 | CONTRACT_PO, S001 at 9,169 (RC-2025-011 rate 9,168.71), value 1,37,531 | ✓ test_engine, except the printed PO number: ours is one higher (open question, PR-26-00174/00175) |
| 2 | Ex 2: PR-26-00045/1, CHK1, ITM-1037, 11 NOS, 2026-11-18 | CONTRACT_PO, S021 at 2,439 via PDF-only RC-2026-031 (starts 11-15, zero consumed), value 26,829 | ✓ test_engine, except the printed PO number: ours is one higher (open question, PR-26-00174/00175) |
| 3 | Ex 3: PR-26-00004/1 (free text "brg 6308 ZZ") + 00026/1, CHK1, ITM-1022 | Clubbed; RC-2026-002 out of ceiling; valued at lowest applicable contract rate, 2,20,256; RFQ, suggest S014, S013, S016 | ✓ test_engine |
| 4 | Ex 4: PR-26-00034/1 + 00032/1, PUN1, ITM-1009 | Clubbed; RC-2026-015 (lower rate) lacks ceiling, so RC-2026-013 is used: CONTRACT_PO S007 at 7, value 32,547 | ✓ test_engine, except the printed PO number: ours is one higher (open question, PR-26-00174/00175) |
| 5 | Ex 5: PR-26-00146/1, 00144/1, 00145/1, CHK1, ITM-1038 | One requirement of 3 lines, value 1,26,472; SPOT_PO S024 at 166 | ✓ test_engine, except the printed PO number: ours is one higher (open question, PR-26-00174/00175) |
| 6 | Ex 6: PR-26-00106/1 (PUN1) and 00103/1 (CHK1, free text), ITM-1044 | Two requirements (different plants). PUN1 one: valued at 21.19 (latest PO), value 1,56,170; SPOT_PO S027 at its own reference price 21.59 | ✓ test_engine, except the printed PO number: ours is one higher (open question, PR-26-00174/00175) |
| 7 | Ex 7: PR-26-00088/1, free text "hyd hose 1/2 inch 2 wire" | Matches ITM-1035; SPOT_PO S023 at 392, value 97,955 | ✓ test_engine, except the printed PO number: ours is one higher (open question, PR-26-00174/00175) |
| 8 | Ex 8: PR-26-00059/1, PUN1, ITM-1026, Emergency | EMERGENCY_PO S014 at 106, value 2,53,184 (above 2 lakh, at or below 5 lakh) | ✓ test_engine, except the printed PO number: ours is one higher (open question, PR-26-00174/00175) |
| 9 | Ex 9: PR-26-00089/1, free text "CMM calibration service" | ITM-1066; RFQ, suggest S043, S044, S042, value 3,36,562 | ✓ test_engine |
| 10 | Ex 10: PR-26-00050/1, PUN1, ITM-1006 | RC-2026-005 does not apply (S004 Blocked) and is not used for valuation; standard price 365, value 80,300; never bought, so RFQ, suggest S003, S002, S005 | ✓ test_engine |
| 11 | Ex 11: PR-26-00100/1, CHK1, ITM-1034 | RFP, value 20,70,780 (D1 tie, see below); suggest S020, S017, S019, S018: only 4 exist (D9) | ✓ test_engine |
| 12 | Ex 12: PR-26-00047/1, free text "eot crane 5 ton" | ITM-1071 Capex; CAPEX_SOURCING, suggest S045, S047, S020, S048, S046, value 60,36,704 | ✓ test_engine |
| 13 | Ex 13: PR-26-00170/1 "Drinking water purifier 50 LPH" | NEW, NEW_ITEM_SOURCING, value 1,41,100 (requester estimate), not clubbed, no suggestions | ✓ test_engine |
| 14 | Ex 14: PR-26-00031/1 + 00035/1, and 00034/1 + 00032/1, PUN1, ITM-1009 | Two requirements (clubbing anchors on the first line: 00035 need-by 11-17 is 8 days from 11-25, so it does not join; it is 5 days from 11-12, so it joins). Both CONTRACT_PO S007 on one PO (first lines 20 h 25 m apart). Second requirement value 23,227 | ✓ test_engine, except the printed PO number: ours is one higher (open question, PR-26-00174/00175) |

## Worked preferred-supplier lists (as of 2026-11-01)

| # | Case | Expected | Status (after F6) |
|---|---|---|---|
| 15 | ITM-1048 Nitrile coated gloves | 1 S029, 2 S030; S031 excluded (Inactive) | ✓ test_preferred |
| 16 | ITM-1036 Pneumatic cylinder 50x100 | 1 S023, 2 S022, 3 S024 | ✓ test_preferred |
| 17 | ITM-1016 MIG wire ER70S-6 1.2mm | 1 S009 (holds contract), 2 S010; equal PO count and recency, so the contract breaks the tie | ✓ test_preferred |

## Boundaries and data edge cases

| # | Case | Expected | Status (after F6) |
|---|---|---|---|
| 18 | PR-26-00036/1 FRL unit, CHK1, requirement date 2026-11-14, one day before RC-2026-031 starts (D7) | Contract does not apply; route decided by 5.3–5.6 | ✓ test_engine |
| 19 | Exact 24 h pair: PR-26-00055/1 (11-10 18:00) and 00053/1 (11-11 18:00), PUN1 | Not on one PO: no shared supplier (00055 is also Emergency, so its route may differ) | ✓ test_engine |
| 20 | Exact 24 h pair: PR-26-00099/1 (11-10 18:00) and 00053/1 (11-11 18:00), PUN1 | Not on one PO: no shared supplier | ✓ test_engine |
| 21 | Exact 24 h pair: PR-26-00011/1 (11-14 18:00) and 00166/1 (11-15 18:00), PUN1 | Not on one PO: no shared supplier | ✓ test_engine |
| 22 | Exact 24 h pair: PR-26-00011/1 (11-14 18:00) and 00166/3 (11-15 18:00), PUN1 | Not on one PO: 00166/3 is Capex, so sourcing, never combined | ✓ test_engine |
| 23 | Synthetic: two PO requirements, same plant, route and supplier, first lines exactly 24 h 00 m apart (D6) | One PO | ✓ test_consolidation (synthetic) |
| 24 | Synthetic: same as 23 but 24 h 01 m apart | Two POs | ✓ test_consolidation (synthetic) |
| 25 | Synthetic: two lines, same item and plant, created 1 day apart, need-by exactly 7 days apart (D5) | One requirement | ✓ test_clubbing |
| 26 | Synthetic: two lines, same item and plant, created exactly 14 calendar days apart (elapsed may be under or over 14 × 24 h), need-by 2 days apart (D4) | One requirement | ✓ test_clubbing |
| 27 | ITM-1034 same-date tie: POs 7300215 (CHK1, 40,929.88) and 7300220 (PUN1, 41,415.60), both 2026-04-10 (D1) | Highest PO number wins: valuation 41,415.60; S020 reference price for ITM-1034 also 41,415.60 | ✓ test_engine |
| 28 | D2: PR-26-00069/1 + 00091/1, CHK1, ITM-1017 argon (latest PO from Blocked S011) | Clubbed, 382 CYL, value 5,65,001 (1,479.06), not 6,16,598; RFQ | ✓ test_engine |
| 29 | D2: PR-26-00058/1, CHK1, free text "Cutting wheel 14 inch", Emergency | ITM-1020, value 4,24,920 (212.46, Blocked S011 PO), EMERGENCY_PO | ✓ test_engine |
| 30 | D2: PR-26-00122/1, PUN1, ITM-1020, 4100 NOS | Value 8,71,086 (212.46), RFQ | ✓ test_engine |
| 31 | D2: PR-26-00083/1, CHK1, free text "Safety goggles clear", 180 NOS | ITM-1050, value 23,319 (129.55, Inactive S031 PO), SPOT_PO | ✓ test_engine |
| 32 | D2: PR-26-00060/1, CHK1, "Safety goggles clear", 820 NOS, Emergency | Not clubbed with 00083 (need-by 18 days apart); value 1,06,231, EMERGENCY_PO | ✓ test_engine |
| 33 | PR-26-00172/1, quantity 0 | NOT_PROCESSED, reason: quantity must be positive | ✓ test_engine |
| 34 | PR-26-00173/1, plant PUN2 | NOT_PROCESSED, reason: unknown plant | ✓ test_engine |
| 35 | PR-26-00171/1 "Ultrasonic thickness gauge" | NEW, NEW_ITEM_SOURCING, value 1,05,600 (requester estimate), no suggestions | ✓ test_engine |

## LLM resilience (app tests; DECISIONS.md D32)

The LLM is replaced by a fake that raises on demand; no test calls a real model.

| # | Case | Expected | Status (after F6) |
|---|---|---|---|
| 36 | `LLM_MODELS=a,b`; model a returns 429 every time | Brief retry on a, then b answers; the result records model b | pending |
| 37 | Model a returns 503, then a timeout; model b answers | Moves to b after the retries; records b | pending |
| 38 | Every model fails | A clear error naming the models tried; no draft is created; the failure is logged | pending |
| 39 | Model a returns 400 (bad request, not transient) | No retry or fallback that could hide a bug; a clear error | pending |
| 40 | Process a batch, then reprocess it under an approved amendment, with the LLM fake set to raise on any call | Both runs complete; the fake was never called | pending |
| 41 | Amendment review: hand-edit the LLM draft (e.g. change a limit) | The edited JSON is validated, diffed and impact-previewed exactly like a draft; an invalid edit cannot be approved | pending |
| 42 | Amendment review with every model down: start from the current version, edit, approve | A new version is created with no LLM call, `drafted_by` = the user | pending |
| 43 | Chat: LLM fails on "need 200 nitrile gloves for Chakan by next Friday, urgent" | The pattern reader gets qty 200, plant CHK1, need-by = next Friday's date, urgency Emergency; the matcher finds ITM-1048; the assistant says the AI is unavailable and carries on | pending |
| 44 | Chat fallback with a missing field ("need gloves") | Asks for quantity, plant and need-by; never invents an item code | pending |
| 45 | Any LLM failure in chat or amendment drafting | Shown to the user in plain words and written to the log; never shown as a wrong answer | pending |

