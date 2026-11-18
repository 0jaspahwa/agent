# Policy document schema (schema_version 1)

A policy version is **one JSON document**. The deterministic engine reads it and never contains policy numbers or rule order itself. Amending the policy means producing a new document (by hand, or drafted by the LLM from an amendment text), validating it, and approving it. The engine code does not change.

| File | Role |
|---|---|
| [`backend/policies/v5.0.json`](../backend/policies/v5.0.json) | The v5.0 document |
| [`backend/engine/logic.py`](../backend/engine/logic.py) | Evaluates JSON Logic expressions (section 7) |
| [`backend/engine/facts.py`](../backend/engine/facts.py) | The fact catalogue: every field an expression may read (section 8) |
| [`backend/engine/policy_check.py`](../backend/engine/policy_check.py) | Validates a document before approval (section 9) |
| [`backend/engine/policy.py`](../backend/engine/policy.py) | Applies overrides, derived facts and the ordered rules to computed facts |

## 1. Top-level shape

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | string | Version of *this* schema, `"1"`. |
| `policy_id` | string | `"CORVO-PROC-POL-04"`. Same for every version. |
| `version` | string | `"5.0"`, `"5.1"`, … Must differ from the version it supersedes. |
| `effective_from` | date `YYYY-MM-DD` | First requirement date this version applies to. |
| `supersedes` | string or null | The version this one replaces (`null` for 5.0). |
| `source_document` | string | Where the content came from (PDF, amendment file, chat). |
| `change_summary` | string | One or two sentences for the version history. |
| `parameters` | object | Numbers, windows, lists and settings (section 2). |
| `overrides` | list | Scope-specific parameter values, e.g. one plant (section 3). |
| `derived_facts` | list | Named expressions the rules can use (section 4). |
| `line_checks` | list | Per-line validity checks giving `NOT_PROCESSED` (section 5). |
| `line_flags` | list | Per-line notes that never stop a line (section 5). |
| `rules` | list, **ordered** | Decision rules; the first whose `when` is true decides (section 6). |
| `translation_notes` | list of strings, optional | Points the LLM was unsure about when drafting from an amendment. Shown to the approver. |

**Which version applies.** The engine picks the version with the latest `effective_from` on or before the **requirement date**, which is the creation date of the requirement's first line (2.3). Clubbing needs its windows before the requirement exists, so it uses the version in force on the first line's creation date, which is the same date. Every decision records `policy_version`. Approval (who, when) is stored by the app alongside the document, not inside it.

## 2. Parameters

Parameters are grouped objects. Any parameter object may carry `clause` (the policy clause), `text` (the policy's words) and `decisions` (DECISIONS.md entries). Code ignores these three keys; people and the diff screen use them.

**Limits store their own comparison operator.** `{"value": 200000, "operator": "<"}` means "below 2,00,000". Rules never write `<` or `<=` against a limit; they call `meets_limit`. Changing "below" to "at or below" is a one-field edit in one place.

**Windows store length, unit and whether the far end counts.** `{"length": 14, "unit": "calendar_days", "inclusive": true}`. `unit` is `calendar_days` or `hours`. History windows add `include_reference_date: false`: a PO dated on the requirement date is not "before" it (D3).

| Parameter | v5.0 value | Clause / decision |
|---|---|---|
| `limits.emergency_po` | `500000`, `<=` | 5.3, D10 |
| `limits.spot_po` | `200000`, `<` | 5.4 |
| `limits.rfq` | `1000000`, `<` (RFP in 5.6 is "not below" this) | 5.5, 5.6 |
| `clubbing.creation_window` | 14 calendar days, inclusive, from the first line | 2.2, D4 |
| `clubbing.need_by_window` | 7 calendar days either side, inclusive, from the first line | 2.2, D5 |
| `consolidation.window` | 24 hours, inclusive, from the first requirement on the PO | 7.1, D6 |
| `contracts.validity` | start and end inclusive | 4.1, D7 |
| `contracts.ceiling` | consumed + value `<=` ceiling | 4.2 |
| `contracts.selection` | `lowest_rate_with_ceiling` | 4.3 |
| `history.valuation_window` | 365 calendar days, far end inclusive, requirement date excluded | 3.1(b), D3, D8 |
| `history.purchase_window` | 365, same | 5.3, 5.4 |
| `history.preferred_window` | 548, same | 6.1, 6.3 |
| `valuation.include_non_active_suppliers` | `true` | 3.1(b), D2 |
| `valuation.tie_break` | `highest_po_number` | D1 |
| `valuation.new_item_price` | `requester_estimate` | 1.2 |
| `ranking.recency_buckets` | ≤ 90 days → 1.0, ≤ 365 days → 0.5, older → 0.0 | 6.2, D8 |
| `ranking.category_topup` | `on_time_pct/100 + quality_rating/5`, equal weights | 6.4 |
| `ranking.reference_price` | latest PO in the preferred window, else latest contract rate; tie → highest PO number | 6.3, D1 |
| `ranking.preferred_score.weights` | po_count 1, recency 5, contract_held 2, on_time 1, quality 1 (on-time ÷ 100, quality ÷ 5) | 6.2, D24 |
| `ranking.tie_break` | equal scores → `supplier_id` ascending, for both the preferred list and the category top-up | 6.2, 6.4, D13 |
| `matching.*` | noise phrases, abbreviations, inch symbols; `number_weight` 2, `min_word_coverage` 0.75, `match_threshold` 0.6, `ambiguity_margin` 0.02, `ambiguity_floor` 0.3, `word_similarity` 0.8, `fuzzy_min_word_length` 4 (how they are used: D20, D21, `engine/matching.py`) | 1.1, D20, D21 |
| `intake.urgency_values` / `default_urgency` / `urgency_words` | `normal → Normal`, `emergency → Emergency` (case-insensitive); blank or unknown → `Normal`; `urgent`, `urgently`, `asap`, `emergency` | D19 |

### Plain lists and settings

Four things that look like code are data. An amendment can change any of them without a code change.

| Parameter | v5.0 value | What it controls |
|---|---|---|
| `clubbing.match_on` | `["item_code", "plant"]` | The **clubbing key**: fields that must be equal for a line to join a requirement (2.2). Allowed: any PR column, or `category`, `item_type`. Adding `"department"` would stop clubbing across departments. |
| `clubbing.order_by` | `["created_at", "pr_no", "pr_line"]` | The order lines are taken in (2.2). |
| `consolidation.match_on` | `["supplier_id", "plant", "route"]` | The **consolidation key**: fields that must be equal for requirements to share a PO (7.1). Allowed: `supplier_id`, `plant`, `route`, `decision`, any PR column. |
| `valuation.price_sources` | `["contract_to_be_used", "lowest_applicable_contract_rate", "latest_po_in_window", "standard_price"]` | The **valuation price order** (3.1): the rate of the contract that will be used; else, if every applicable contract is out of ceiling, the lowest applicable rate; else the latest PO in `history.valuation_window`; else the item master standard price. The first source that gives a price wins. |
| `suppliers.allowed_statuses` | each use → `["Active"]` | **Which supplier statuses count, per use**: `receive_po` and `be_suggested` (5.7), `count_for_purchase_history` ("bought from an Active supplier", 5.3/5.4), `hold_applicable_contract` (4.1), `join_preferred_list` (6.1). They are separate lists, so an amendment can, for example, let Inactive suppliers be suggested without letting them receive POs. Valuation (3.1b) is governed by `valuation.include_non_active_suppliers` instead (D2). |

## 3. Overrides (scope-specific parameters)

```json
"overrides": [
  {
    "id": "OV-1",
    "parameter": "limits.spot_po",
    "when": {"==": [{"var": "line.plant"}, "CHK1"]},
    "set": {"value": 100000},
    "clause": "Amendment A-2 §1"
  }
]
```

- `parameter` is a dotted path to an existing parameter object.
- `set` replaces only the listed fields; each must already exist in that parameter, with the same type.
- `when` is evaluated at the **override stage**, on the requirement's first line and its matched item only (`line.*`, `item.*`; section 8.1). Some parameters, like the clubbing windows, are needed while clubbing, before a requirement exists. That is why `requirement.*`, `plant.*`, `derived.*` and `params.*` cannot be used here, and the validator rejects them. An override whose condition depends on the value or on history belongs in a rule instead.
- If several overrides for one parameter match, the **first in the list wins**.
- The document itself is never changed; `engine.policy.resolve_parameters` returns the effective values. v5.0 has no overrides.

A plant-specific change can be made in two ways. A **different number** for one plant is an override, as above. A **different decision** for one plant is a rule whose `when` includes `{"==": [{"var": "plant.plant"}, "CHK1"]}` (section 6).

## 4. Derived facts

```json
{"name": "is_emergency", "clause": "2.3",
 "description": "The requirement is an emergency if any of its lines is marked Emergency.",
 "expr": {"some": [{"var": "lines"}, {"==": [{"var": "urgency"}, "Emergency"]}]}}
```

Derived facts are evaluated in list order before the rules, at requirement level, and stored at `derived.<name>`. A derived fact may use earlier ones, and rules may use all of them. This is how an amendment introduces a fact the catalogue lacks, without code. For example, a price-variance rule needs:

```json
{"name": "price_premium_pct", "description": "Valuation price above standard price, in percent",
 "expr": {"*": [100, {"/": [{"-": [{"var": "requirement.valuation_price"}, {"var": "item.standard_price"}]},
                           {"var": "item.standard_price"}]}]}}
```

For a new item, `item.standard_price` is missing, so the arithmetic gives `null`, and any comparison on `derived.price_premium_pct` is false (section 7).

## 5. Line checks and line flags

```json
{"id": "V3", "title": "No duplicate PR line",
 "when": {"==": [{"var": "line.is_duplicate"}, true]},
 "reason": "Duplicate of an earlier line with the same PR number and line number; only the first is processed"}
```

**When they run.** Both lists are evaluated per PR line at the **line-check stage**: after the line's item is matched, before clubbing (section 8.1). The line is checked under the policy version in force on its creation date. If the creation time is unreadable, the latest approved version is used, so the line can still be checked and reported (D19).

**`line_checks`.** If any `when` is true, the line becomes `NOT_PROCESSED`. Every reason that fired is kept, and the line never clubs.

| id | When | Reason |
|---|---|---|
| V1 | quantity ≤ 0 | Quantity is zero or negative |
| V2 | plant not in the plant master | Plant is not in the plant master |
| V3 | an earlier line has the same pr_no and pr_line | Duplicate; only the first is processed |
| V4 | need-by missing or unreadable | Need-by date is missing or unreadable |
| V5 | unit differs from the matched item's unit (case and punctuation ignored) | The value cannot be computed |
| V6 | quantity missing or not a number | Quantity is missing or not a number |
| V7 | creation time missing or unreadable | Creation time is missing or unreadable |

**`line_flags`** have the same shape, with `message` instead of `reason`. A flag never stops a line; it travels with the line to the reason text.

| id | When | Message |
|---|---|---|
| F1 | need-by earlier than the creation date | Need-by date is earlier than the creation date |
| F2 | urgency blank or not in `intake.urgency_values` | Treated as Normal |
| F3 | item code given but not in the item master | The description was matched instead |
| F4 | a valid code, but the description clearly names another item | The item code was used (policy 1.1) |
| F5 | the description contains an `intake.urgency_words` word but the urgency is not Emergency | The field was used |
| F6 | unit missing | The item's unit was assumed |

The policy PDF has none of these; they are our decisions (D19, D45). An amendment can remove, add or reword any of them, as data.

## 6. Rules

The list order **is** the policy's order. The first rule whose `when` is true decides. A new rule goes in at the position the amendment says, with an id such as `"5.3A"`. Ids must be unique.

| Field | Meaning |
|---|---|
| `id` | Clause number, quoted in every decision's `reason`. |
| `title` | Short name for the buyer screen. |
| `clause_text` | The policy's wording. Shown next to the decision; never parsed. |
| `when` | JSON Logic expression over requirement-level facts (section 8). |
| `then.decision` | `PO` or `SOURCING_REQUEST`. |
| `then.route` | `CONTRACT_PO`, `EMERGENCY_PO`, `SPOT_PO`, `RFQ`, `RFP`, `CAPEX_SOURCING` or `NEW_ITEM_SOURCING` (the output format's fixed list). |
| `then.supplier` | PO: `contract_supplier` (the contract chosen under 4.3) or `preferred_rank_1` (1st on the preferred list). Sourcing: `suggest` (top `suggest_count`, topped up per 6.4) or `none`. |
| `then.price` | PO: `contract_rate` or `reference_price` (6.3). Sourcing: `none`. |
| `then.suggest_count` | Whole number; 0 for every PO and for new items. If fewer eligible suppliers exist, fewer are suggested (D9). |
| `then.flags` | Optional labels for the buyer, e.g. `capex_approval_required`. |

5.7 (never a Blocked or Inactive supplier) is not a rule. It is enforced on every supplier strategy through `suppliers.allowed_statuses`.

v5.0 has rule `1.2` (new item) first, then `5.1` to `5.6`. Rule 1.2 comes from section 1 of the PDF, but it decides a route. A new item has no item type, so it would otherwise fall through to the value rules.

**Rule 1.2 must stay first.** Rule 5.6 is a negation (`! meets_limit(value_inr, limits.rfq)`), and a comparison on a missing value is false, so its negation is true. A new item without an estimated price has no `value_inr` (D12). If it ever got past 1.2, it would fall to 5.6 and become an RFP. An amendment may add rules, but nothing may move ahead of 1.2 unless that rule cannot match a new item.

## 7. Operators and missing values (`backend/engine/logic.py`)

| Operators | Notes |
|---|---|
| `var` | `{"var": "a.b"}` or `{"var": ["a.b", default]}`. The default applies when the field is absent **or null**. |
| `==` `!=` (aliases `===` `!==`) | Python equality, **no type coercion**. |
| `<` `<=` `>` `>=` | Exactly two arguments. |
| `and` `or` `!` `!!` `if` | As in JSON Logic; `and`/`or` stop at the first deciding value. |
| `in` | Value in a list, or substring in a string. |
| `+` `-` `*` `/` `min` `max` | Arithmetic. |
| `some` `all` `none` | `[array, predicate]`. The predicate sees **one element** as its data. `all` of an empty list is false. |
| `date_diff_days` | `[a, b]` → whole calendar days a − b. Accepts dates or timestamps (time ignored). |
| (numbers) | Every number is an exact decimal: a policy number or a float fact is read as the decimal it was written as, and `/` divides in decimal (D11). |
| `meets_limit` | `[value, "limits.spot_po"]` → `value <operator> limit.value`, using the operator stored in the limit. |

**Three kinds of trouble, handled differently**

| Situation | Example | What happens |
|---|---|---|
| **Unknown field**: the name is not in the fact catalogue | `history.bought_from_actve` (typo), `item.brand` (invented) | `policy_check.validate` reports an error, so the version **cannot be approved**. It never reaches a batch run. |
| **Missing value**: a catalogue field with no value on this line or requirement | blank `estimated_unit_price`; `item.category` for a new item; `contract.rate` when no contract applies | No exception. Any comparison (`<` `<=` `>` `>=` `meets_limit`) with a missing operand is **false**. Arithmetic and `date_diff_days` on it give `null`, and `==` compares with `null` normally. The evaluator appends the field's path to the caller's `missing` list (`lines[].<field>` inside `some`/`all`). `engine.policy.decide` returns these per rule, so the reason can say, for example, "5.3A not met: item.category missing". |
| **Mixed types or malformed expression** | `"10" < 5`, an unknown operator, a comparison with one argument | `LogicError` is raised. The validator catches most of these first. |

**Watch out for negation.** `!` turns a false-because-missing comparison into **true**. Only negate a comparison on a field that cannot be missing when the rule is reached. Rule 5.6 (`! meets_limit(value_inr, limits.rfq)`) is safe: `value_inr` is missing only for a new item without an estimate, and rule 1.2 catches every new item first. The test `test_negating_a_missing_comparison_gives_true` pins this behaviour down.

## 8. Facts the expressions can read (`backend/engine/facts.py`)

A type ending in `?` may be missing on a given line or requirement. Paths not listed here (and not `derived.*` or an existing `params.*`) are rejected by the validator.

**Requirement level** (rules and derived facts)

| Path | Type | Content |
|---|---|---|
| `requirement.id` | string | Our requirement id |
| `requirement.date` | date | First line's creation date (2.3) |
| `requirement.created_at` | datetime | First line's creation timestamp |
| `requirement.plant` | string | |
| `requirement.item_code` | string | Resolved code, or `NEW` |
| `requirement.is_new_item` | boolean | |
| `requirement.total_quantity` | number | Sum over its lines |
| `requirement.line_count` | integer | Number of PR lines |
| `requirement.distinct_requesters` | integer | |
| `requirement.distinct_departments` | integer | |
| `requirement.lead_time_days` | integer? | First line's `need_by_date` − requirement date |
| `requirement.value_inr` | number? | 3.1 value; missing only for a new item with no estimate |
| `requirement.valuation_price` | number? | The unit price used for the value |
| `requirement.valuation_source` | string? | Which `valuation.price_sources` entry gave it |
| `contract.usable` | boolean | 4.1–4.3 pass for some contract |
| `contract.any_applicable` | boolean | 4.1 passes for some contract, even if out of ceiling |
| `contract.remaining_ceiling` | number? | Ceiling left on the contract that would be used, before this requirement |
| `contract.lowest_applicable_rate` | number? | |
| `contract.<register column>` | ?, all | `contract_id`, `supplier_id`, `supplier_name`, `start_date`, `end_date`, `value_cap`, `consumed_value`, plus the contract line's `rate`, for the contract that would be used |
| `contract.supplier.<supplier column>` | ?, all | That contract's supplier master row |
| `history.bought_from_active` | boolean | A PO in `history.purchase_window` from a supplier whose status is in `count_for_purchase_history` |
| `history.po_count` | integer | POs for the item in the purchase window, any supplier |
| `history.active_po_count` | integer | Same, allowed statuses only |
| `history.distinct_active_suppliers` | integer | Distinct allowed-status suppliers with a PO in the purchase window |
| `history.days_since_last_po` | integer? | Requirement date − latest PO date for the item, any supplier, whole history |
| `history.latest_po_price`, `latest_po_number`, `latest_po_date`, `latest_po_supplier_id` | ? | The PO 3.1(b) would use (valuation window, D1/D2) |
| `preferred.list_size` | integer | Suppliers on the item's preferred list |
| `preferred.rank1.<supplier column>`, `preferred.rank1.reference_price` | ? | The 1st preferred supplier |
| `first_line.<PR column>`, `lines[].<PR column>` | | Every PR column (below); `lines` itself is the list |
| `item.<item column>` | ?, all | Item master row; missing for a new item |
| `plant.<plant column>` | | Plant master row |
| `derived.<name>` | | Results of `derived_facts` |
| `params.<path>` | | Parameters after overrides, read-only |

**Line level** (line checks, flags and overrides; section 8.1 says which): `line.<PR column>` with canonical values (plant and item code upper case; unit upper case without punctuation; urgency mapped through `intake.urgency_values`), plus the computed line facts; `item.<item column>` for the matched item (missing for a new item); `plant.<plant column>` and `match.*` (line checks and flags only); `params.<path>` (line checks and flags only).

### 8.1 Which facts exist at each stage

The pipeline runs in stages, and each kind of expression runs at one of them. A fact that does not exist yet at that stage cannot be read. The validator rejects it with "not available at the … stage", and an invented name is still reported as "unknown field".

| Stage | Expressions evaluated there | Facts available | Why |
|---|---|---|---|
| **Line check** | `line_checks`, `line_flags` | `line.*` (including the computed `is_duplicate`, `uom_mismatch`, `urgency_recognised`, `description_says_urgent`), the matched `item.*`, `plant.*`, `match.*` (`status`, `score`, `item_code_unknown`, `description_disagrees`), `params.*` | One line after item matching, before clubbing: there is no requirement, contract or history yet |
| **Clubbing** | `overrides` (they set the parameters, including the clubbing windows themselves) | `line.*` and the matched `item.*` only | Clubbing builds the requirements, so none exists yet; `params.*` is what the overrides produce |
| **Rules** | `derived_facts`, `rules` | everything in the requirement-level table above, plus `derived.*` and `params.*` (after overrides) | After clubbing, contract selection, valuation and ranking |

**The plant has three spellings, each valid at its own stage.** `line.plant` is the raw PR column (line checks, overrides). `plant.plant` is the plant master row (line checks: missing if the plant is unknown; rules). `requirement.plant` is the requirement's plant (rules); `first_line.plant` is the same value. The Gemini drafts in `docs/spike_results/` used all three correctly.

**Raw columns readable in full**

| Source | Columns |
|---|---|
| PR line | `pr_no`, `pr_line`, `created_at`, `requester`?, `department`?, `plant`, `item_code`?, `description`, `quantity`, `uom`?, `estimated_unit_price`?, `need_by_date`?, `urgency`? |
| Item master | `item_code`, `description`, `uom`, `category`, `item_type`, `standard_price` |
| Supplier master | `supplier_id`, `name`, `city`, `categories`, `status`, `on_time_pct`, `quality_rating` |
| Plant | `plant`, `name` |
| Contract | `contract_id`, `supplier_id`, `supplier_name`, `start_date`, `end_date`, `value_cap`, `consumed_value`, `rate` |

Only `derived.*` is computed from the policy. The engine computes everything else, and these facts are documented here before the engine exists (the engine build implements them).

## 9. Validation before approval (`backend/engine/policy_check.py`)

`validate(policy, previous)` returns `(errors, warnings)`. Any error blocks approval.

- **Document:** all top-level keys present, and none unknown. `schema_version` is `"1"`. `effective_from` is a date. Against the current version: `version` is new and `supersedes` names the current version.
- **Parameters:** every parameter the engine needs is present.
  - `ranking.tie_break` orders by `supplier_id`.
  - Each limit has a numeric `value` and an `operator` in `< <= > >=`.
  - Each window has a positive `length`, a known `unit` and a boolean `inclusive`.
  - The plain lists are non-empty and use allowed values.
  - Every `allowed_statuses` use is present, and `include_non_active_suppliers` is a boolean.
- **Expressions** (overrides, derived facts, line checks, rules):
  - Only known operators.
  - Every path is in the catalogue for its level, or is a derived fact defined *earlier*, or an existing parameter.
  - Every `meets_limit` names an existing limit.
- **Overrides:** the target parameter exists, and `set` only uses its existing fields, with the same types.
- **Rules:** unique ids, a known `decision` and `route`, a `supplier` and `price` that suit the decision, and `suggest_count` a whole number (0 for a PO). A rule whose `when` is literally `true` before the end of the list gives a warning, because the rules after it can never apply.

## 10. Worked example: rule 5.3, the emergency rule

```json
{
  "id": "5.3",
  "title": "Emergency PO",
  "clause_text": "Emergency, value at or below 5,00,000, and the item was bought from an Active supplier in the last 365 days. 1st preferred supplier at its reference price.",
  "when": {"and": [
    {"==": [{"var": "derived.is_emergency"}, true]},
    {"meets_limit": [{"var": "requirement.value_inr"}, "limits.emergency_po"]},
    {"==": [{"var": "history.bought_from_active"}, true]}
  ]},
  "then": {"decision": "PO", "route": "EMERGENCY_PO", "supplier": "preferred_rank_1", "price": "reference_price", "suggest_count": 0}
}
```

**Field by field**

| Field | What it says | Where its inputs come from |
|---|---|---|
| `"id": "5.3"` | The clause number. Every decision this rule makes says "5.3" in its reason. | Policy PDF section 5. |
| `"title"` | "Emergency PO", the heading the buyer sees. | |
| `"clause_text"` | The policy's own sentence, shown next to the decision. The engine never reads it. | Policy PDF table row 5.3. |
| `"when"` → `"and": [...]` | All three conditions must hold. `and` stops at the first false one. | |
| condition 1: `{"==": [{"var": "derived.is_emergency"}, true]}` | The requirement is an emergency. | `derived.is_emergency` is defined in this same document (`derived_facts`): any line with `urgency == "Emergency"` (2.3). Changing what "emergency" means is a data edit too. |
| condition 2: `{"meets_limit": [{"var": "requirement.value_inr"}, "limits.emergency_po"]}` | The value passes the emergency limit. | `requirement.value_inr` is computed by the engine (3.1). `limits.emergency_po` is `{"value": 500000, "operator": "<="}`, so this reads "value ≤ 5,00,000". The rule itself has no number and no `<=`. If the value were missing, this condition would be false and `requirement.value_inr` would be reported as missing. |
| condition 3: `{"==": [{"var": "history.bought_from_active"}, true]}` | The item has a PO in the purchase window from an allowed-status supplier. | Computed by the engine using `history.purchase_window` (365 days, D3) and `suppliers.allowed_statuses.count_for_purchase_history` (`["Active"]`). Unlike valuation (D2), this never counts Blocked or Inactive suppliers. |
| `"then.decision": "PO"` | A purchase order is placed directly, without quotes. | |
| `"then.route": "EMERGENCY_PO"` | The route written to the output row. | Output format's route list. |
| `"then.supplier": "preferred_rank_1"` | The 1st supplier on the item's preferred list as of the requirement date, among `allowed_statuses.receive_po`. | Section 6 of the policy; `ranking.*`. |
| `"then.price": "reference_price"` | That supplier's own latest PO price in 548 days, else its latest contract rate. This is **not** the valuation price (Ex 6 trap). | 6.3, `ranking.reference_price`. |
| `"then.suggest_count": 0` | A PO suggests no one. | |

**Evaluated on worked example 8** (PR-26-00059/1, PUN1, ITM-1026, Emergency, 2,380 NOS). Rules 1.2, 5.1 and 5.2 are false: the item is known, it is Material, and there is no usable contract. Then for 5.3:
1. `derived.is_emergency` = true.
2. `2,53,184 <= 5,00,000` is true.
3. `history.bought_from_active` = true.

The outcome is EMERGENCY_PO to S014 at its reference price 106. Rule 5.4 is never reached, so the 2-lakh spot limit does not matter. That is the point of Ex 8.

**Common hand edits**

- *Raise the emergency limit to 7.5 lakh:* set `parameters.limits.emergency_po.value` to `750000`. Rule 5.3 is untouched.
- *Make it "below" instead of "at or below":* set `operator` to `"<"`.
- *A different emergency limit at CHK1 only:* add an override `{"id": "OV-1", "parameter": "limits.emergency_po", "when": {"==": [{"var": "line.plant"}, "CHK1"]}, "set": {"value": 300000}}`.
- *Apply 5.3 only at CHK1:* add `{"==": [{"var": "plant.plant"}, "CHK1"]}` to the `and` list.
- *Insert a rule before 5.3:* add an object with a new id (`"5.2A"`) at that position in `rules`.

## 11. Known limits of the format

1. **History aggregates are engine facts.** Windows and statuses are parameters, but a genuinely new aggregate (e.g. "bought at least 3 times from the same supplier") needs a new catalogue fact, which is a code change. The wide catalogue in section 8 reduces how often that happens.
2. **`some`/`all` predicates see only the element** (standard JSON Logic). A predicate cannot compare a line with an outer fact or a parameter. A derived fact over `first_line` or a requirement-level fact usually covers the need.
3. **Outcomes use fixed strategies.** `supplier` and `price` choose from enumerations. An outcome of a new kind (e.g. "PO to the 2nd preferred supplier") needs a new strategy in code.
4. **RFP is written as "not below the RFQ limit"** so that one number defines the 5.5/5.6 boundary. Changing `limits.rfq` moves both rules together. See section 7 for why the negation is safe there.
5. **Clubbing, valuation, contract selection and consolidation are algorithms with parameters.** Their windows, keys, orders and statuses are data. Their structure is code.
6. JSON Logic is verbose to read, so the amendment screen must render rules and diffs in plain language, not raw JSON.
