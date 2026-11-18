# Real-LLM rehearsal, run 1 (17 Nov 2026)

`python scripts/rehearse_amendments.py --llm`: in-process app, temporary SQLite database, the app's own draft
endpoint, model list from `.env` (only `LLM_MODEL=gemini-3.6-flash`; `LLM_MODELS` is not set, so there was
no fallback model). Up to two tries per amendment.

**Stopped at A5: the free tier refused the call (HTTP 429).** As agreed, the script stopped there instead of
working around it. The script stopped before printing its report (since fixed). The results below were read
back from the run's database (drafts, draft_info, audit log). Times are from the audit timestamps and include
a few seconds of local work.

| Amendment | Tries | What Gemini returned | Time | Valid | Same decision changes as the hand-made draft (sample batch) | Behaviour cases (`.checks.json`, offline) | `not_expressed` | Label / supersedes | Effective date |
|---|---|---|---|---|---|---|---|---|---|
| A1 limits | 2 | try 1: 503, 503 (retry); try 2: 503, then answered | try 1 ~50 s; try 2 ~100 s | yes | yes (0 = 0: effective after the batch) | 7/7 | `[]`, correct (nothing inexpressible) | 5.1 / 5.0, correct | 2026-12-01, correct |
| A2 Chakan | 1 | answered | ~135 s | yes | yes (0 = 0) | 9/9 | `[]`, correct | 5.1 / 5.0, correct (the app renumbered it 5.2 because 5.1 was taken) | 2026-12-01, correct |
| A3 price variance | 1 | answered | ~140 s | yes | yes (0 = 0) | all passed | `[]`, correct | 5.1 / 5.0, correct (stored as 5.3) | 2027-01-01, correct |
| A4 RFQ ceiling (PDF) | 2 | 503, 503 on both tries | 18 s, 8 s | no draft | (the hand-made draft was used: 5 changes, Run 1 golden) | - | - | - | - |
| A5 Chakan emergency | 1 | **429** | <1 s | - | stopped here | - | - | - | - |
| A6–A9 | 0 | not run | | | | | | | |

**How each LLM draft differs from the hand-made draft:** wording only, plus equivalent ways of writing the
same condition.
- **A1:** the LLM also updated the clause text of rules 5.3 and 5.4.
- **A2:** the LLM wrote `plant.plant` where the hand-made draft has `requirement.plant`; both hold the same value.
- **A3:** the LLM added a limit parameter `limits.price_variance` {15, `>`}, used with `meets_limit`. The
  hand-made draft inlines the 15. The prompt asks for the parameter style.

No drift elsewhere, and no truncation. Each answered draft is the whole policy, about 11.7k–12.9k characters.

**Prompt size:** about 55,000 characters per amendment (54.6k–55.3k), roughly 14k tokens:
- the schema document, about 30k characters;
- v5.0 itself, about 15k;
- the fact catalogue and the instructions.

**Calls:** 11 requests to Gemini: 3 answered, 7 × 503, 1 × 429. All went to `gemini-3.6-flash`. At the time,
the 429 body was not kept, so which quota it hit (per minute or per day) is unknown. `llm/gemini.py` now keeps
Google's reason and the retry delay.

**Not affected by the stop:** every approved draft was withdrawn, and the batch processed by date afterwards
equals the golden file.
