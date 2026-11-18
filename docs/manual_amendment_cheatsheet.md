# Manual amendment cheat sheet

For Run 2 without the AI: **Policy → Edit the current version by hand (no AI)** gives a draft that is an exact copy
of the current version (v5.0) with a new version label. Change it in **Edit the draft (JSON)**, press **Save and
re-check**, and read **What changes**: each edit below must produce the sentence shown, and nothing else may appear
except the metadata lines (version, supersedes, effective from, source document, change summary).

How to read each entry:
- **Says**: what an amendment typically says.
- **Edit**: the JSON, and where it goes. "Replace" means: find that key in the editor and replace its value with
  the block. "Insert" means: paste the block into the `rules` list at the position named, with a comma between
  rules. "Append" means: paste it as the last entry of that list (`"overrides": []` becomes `"overrides": [ {...} ]`).
- **The app shows**: the sentence(s) under What changes, word for word.

Every snippet here is tested (`backend/tests/test_cheatsheet.py`): applied to v5.0 the way the manual draft path
does, validated with no errors, its sentences checked exactly, run on the sample batch, and repeated through the real
draft endpoints. The `<!-- ... -->` comments are read by that test; leave them alone.

Ground rules that apply to every change:
- **Expressions** are JSON Logic: `{"==": [a, b]}`, `{"!=": ...}`, `{"<": ...}`, `{"<=": ...}`, `{">": ...}`,
  `{">=": ...}`, `{"and": [...]}`, `{"or": [...]}`, `{"!": x}`, `{"in": [x, [list]]}`, `{"some": [{"var": "lines"},
  cond]}`, `+ - * /`, plus ours: `{"date_diff_days": [a, b]}` (whole days a minus b) and
  `{"meets_limit": [value, "limits.<name>"]}` (compares with the limit's own operator).
- **Fields a rule or derived fact can read** (stage `requirement`, `backend/engine/facts.py`):
  `requirement.plant`, `requirement.value_inr`, `requirement.date`, `requirement.lead_time_days`,
  `requirement.total_quantity`, `requirement.line_count`, `requirement.is_new_item`,
  `requirement.valuation_price`, `requirement.valuation_source`, `item.category`, `item.item_type`,
  `item.standard_price`, `item.item_code`, `first_line.department`, `first_line.urgency`, `first_line.requester`,
  `first_line.need_by_date`, `lines[].<any PR column>` (inside `some`/`all`/`none`), `history.bought_from_active`,
  `history.po_count`, `history.active_po_count`, `history.days_since_last_po`, `history.latest_po_price`,
  `contract.usable`, `contract.remaining_ceiling`, `preferred.list_size`, `derived.<name>`, `params.<path>`.
- **Fields an override can read** (stage `override`: the requirement's first line and its item, before any
  requirement exists): `line.plant`, `line.department`, `line.urgency`, `line.requester`, `line.quantity`,
  `line.estimated_unit_price`, `item.category`, `item.item_type`, `item.item_code`, `item.standard_price`. Not
  `requirement.*`, `history.*` or `contract.*` (the checker refuses them with the stage named).
- **Values are canonical**: plants `PUN1`, `CHK1`; urgency `Normal` or `Emergency`; categories and item types
  exactly as in the item master (`Lubricants`, `Safety & PPE`, `Material`, `Service`, `Capex`); departments as in
  the batch (`Maintenance`, `Stores`, ...).
- **Rule order decides**: the first rule whose condition holds wins. Keep `1.2` (new item) first and `5.6` (RFP,
  "not below the RFQ limit") last: removing 5.6 leaves requirements no rule decides.
- **A missing value is never a match**: a comparison on a blank field (a new item's category, a value with no
  price) is false, so the next rule decides.

---

## 1. Version label, base version and effective date

**Says:** "Amendment 1 to the procurement policy, version 5.1, effective 1 December 2026."

**Edit:** the top of the document. `version` is the label the app proposed (keep it unless the amendment names one;
a label already used is refused). `supersedes` must stay the version you started from (`"5.0"`). `effective_from` is
the date the amendment states, `YYYY-MM-DD`; if it gives none, ask: the draft cannot be approved without one.
`source_document` names the amendment; `change_summary` lists every clause (section 14).

<!-- case 1 meta -->
<!-- set version -->
```json
"5.1"
```
<!-- set effective_from -->
```json
"2026-12-01"
```
<!-- set source_document -->
```json
"Amendment 1 (PDF received 19 Nov 2026)"
```
<!-- set change_summary -->
```json
"Amendment 1: clause 1 sets the effective date 1 Dec 2026."
```

**The app shows:**
<!-- expect -->
> Version: '5.0' becomes '5.1'
> Effective from: '2026-04-01' becomes '2026-12-01'
> Supersedes: none becomes '5.0'
> Source document: 'Corvo_Procurement_Policy.pdf, version 5.0, effective 1 April 2026' becomes 'Amendment 1 (PDF received 19 Nov 2026)'
> Change summary: 'Baseline policy transcribed from the PDF. Readings of points the PDF leaves open are in DECISIONS.md (D1-D10).' becomes 'Amendment 1: clause 1 sets the effective date 1 Dec 2026.'

---

## 2. A limit's value, and its operator

**Says:** "The spot purchase limit is reduced to ₹1,50,000." / "Spot purchases up to and including ₹2,00,000."

**Edit:** `parameters.limits`. Each limit is `value` (rupees, a plain number: no commas, no ₹), `operator` (`"<"`
for "below" / "less than", `"<="` for "up to" / "at or below" / "not exceeding"), and `text` (free words, for
people). The three limits are `emergency_po` (rule 5.3), `spot_po` (5.4) and `rfq` (5.5; rule 5.6, RFP, is
everything not below it, so changing `rfq` moves the RFQ/RFP boundary too).

### 2a. Value

<!-- case 2a -->
Replace `"spot_po"`:
<!-- set parameters.limits.spot_po -->
```json
{"value": 150000, "operator": "<", "clause": "5.4", "text": "below 1,50,000"}
```

**The app shows:**
<!-- expect -->
> Spot PO limit: below 2,00,000 becomes below 1,50,000

### 2b. Operator (below becomes at or below)

<!-- case 2b -->
Replace `"spot_po"`:
<!-- set parameters.limits.spot_po -->
```json
{"value": 200000, "operator": "<=", "clause": "5.4", "text": "at or below 2,00,000"}
```

**The app shows:**
<!-- expect -->
> Spot PO limit: below 2,00,000 becomes at or below 2,00,000

### 2c. The RFQ limit (moves the RFQ/RFP boundary)

<!-- case 2c -->
Replace `"rfq"`:
<!-- set parameters.limits.rfq -->
```json
{"value": 1500000, "operator": "<", "clause": "5.5", "text": "below 15,00,000 (rule 5.6, RFP, is everything not below it)"}
```

**The app shows:**
<!-- expect -->
> RFQ limit: below 10,00,000 becomes below 15,00,000

---

## 3. A limit that differs for one plant (override)

**Says:** "At the Chakan plant the spot purchase limit is ₹1,00,000."

**Edit:** append to `"overrides"`. `parameter` is the limit's path; `set` holds only the fields that change (same
types as in the limit); `when` reads the first line and its item. An override applies to the whole requirement,
judged on its first line. For each parameter the first matching override wins, so put the most specific first.
Only the limits and the clubbing windows can be overridden (the engine reads the others from the version itself).

<!-- case 3 -->
<!-- append overrides -->
```json
{"id": "OV-1", "parameter": "limits.spot_po", "when": {"==": [{"var": "line.plant"}, "CHK1"]}, "set": {"value": 100000, "text": "below 1,00,000 at CHK1"}}
```

**The app shows:**
<!-- expect -->
> New override OV-1: limits.spot_po gets value 1,00,000, text 'below 1,00,000 at CHK1' when plant is 'CHK1'

---

## 4. A limit that differs for a category, item type, department or urgency (override)

Same as section 3; only `when` changes. Give each override its own `id`.

### 4a. Category

**Says:** "For lubricants the spot limit is ₹50,000."

<!-- case 4a -->
<!-- append overrides -->
```json
{"id": "OV-1", "parameter": "limits.spot_po", "when": {"==": [{"var": "item.category"}, "Lubricants"]}, "set": {"value": 50000}}
```

**The app shows:**
<!-- expect -->
> New override OV-1: limits.spot_po gets value 50,000 when item category is 'Lubricants'

### 4b. Item type

**Says:** "Services may be bought on a spot PO up to ₹3,00,000."

<!-- case 4b -->
<!-- append overrides -->
```json
{"id": "OV-1", "parameter": "limits.spot_po", "when": {"==": [{"var": "item.item_type"}, "Service"]}, "set": {"value": 300000, "operator": "<="}}
```

**The app shows:**
<!-- expect -->
> New override OV-1: limits.spot_po gets value 3,00,000, operator '<=' when item type is 'Service'

### 4c. Department

**Says:** "Requests from Maintenance have an RFQ limit of ₹5,00,000."

<!-- case 4c -->
<!-- append overrides -->
```json
{"id": "OV-1", "parameter": "limits.rfq", "when": {"==": [{"var": "line.department"}, "Maintenance"]}, "set": {"value": 500000}}
```

**The app shows:**
<!-- expect -->
> New override OV-1: limits.rfq gets value 5,00,000 when line.department is 'Maintenance'

### 4d. Urgency

**Says:** "Emergency purchases may go up to ₹7,50,000." (Only an emergency requirement reaches rule 5.3, so
changing `emergency_po` itself does the same; an override is needed when it applies to part of them.)

<!-- case 4d -->
<!-- append overrides -->
```json
{"id": "OV-1", "parameter": "limits.emergency_po", "when": {"==": [{"var": "line.urgency"}, "Emergency"]}, "set": {"value": 750000}}
```

**The app shows:**
<!-- expect -->
> New override OV-1: limits.emergency_po gets value 7,50,000 when urgency is 'Emergency'

### 4e. A mix (plant and category)

**Says:** "At Pune, safety equipment has a spot limit of ₹75,000."

<!-- case 4e -->
<!-- append overrides -->
```json
{"id": "OV-1", "parameter": "limits.spot_po", "when": {"and": [{"==": [{"var": "line.plant"}, "PUN1"]}, {"==": [{"var": "item.category"}, "Safety & PPE"]}]}, "set": {"value": 75000}}
```

**The app shows:**
<!-- expect -->
> New override OV-1: limits.spot_po gets value 75,000 when plant is 'PUN1' and item category is 'Safety & PPE'

---

## 5. How many suppliers a rule suggests

**Says:** "RFQs go to at least four suppliers."

**Edit:** in the rule's `then`, `suggest_count` (a whole number; 0 for a PO rule). Rules that suggest: `5.1` Capex
(5), `5.5` RFQ (3), `5.6` RFP (5). Update `clause_text` to match, so the reason text a buyer reads stays true. The app
suggests as many eligible suppliers as exist, never more (D9).

<!-- case 5 -->
<!-- set rules[5.5].then.suggest_count -->
```json
4
```
<!-- set rules[5.5].clause_text -->
```json
"Value below 10,00,000 (including small items never bought in the last 365 days). Suggest 4 suppliers (6.4)."
```

**The app shows:**
<!-- expect -->
> Rule 5.5 'RFQ' changed (then, clause_text): now applies when requirement value is below 10,00,000 (RFQ limit); outcome: RFQ with 4 suggested suppliers

---

## 6. A new rule

**Edit:** insert into `"rules"` at the position the amendment implies: before the rule it must win over, after the
rule that must win over it. Give it a new `id` (e.g. `5.4A`), a `title`, `clause_text` (the amendment's words), a
`when`, and a `then` copied from an existing rule with the same outcome:

| Outcome | `then` |
|---|---|
| RFQ | `{"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 3}` |
| RFP | `{"decision": "SOURCING_REQUEST", "route": "RFP", "supplier": "suggest", "price": "none", "suggest_count": 5}` |
| Spot PO | `{"decision": "PO", "route": "SPOT_PO", "supplier": "preferred_rank_1", "price": "reference_price", "suggest_count": 0}` |
| Emergency PO | `{"decision": "PO", "route": "EMERGENCY_PO", "supplier": "preferred_rank_1", "price": "reference_price", "suggest_count": 0}` |
| Contract PO | `{"decision": "PO", "route": "CONTRACT_PO", "supplier": "contract_supplier", "price": "contract_rate", "suggest_count": 0}` |

Routes are fixed (the export's route column); a new rule reuses one of them. A rule before `5.2` would take
requirements away from a usable contract: put it after 5.2 unless the amendment says contracts are overridden.

### 6a. Plant

**Says:** "At Chakan, any requirement of ₹50,000 or more that is not on contract goes to RFQ."

<!-- case 6a -->
<!-- insert rules before 5.3 -->
```json
{"id": "5.2A", "title": "Chakan RFQ from 50,000", "clause_text": "At CHK1, a requirement of 50,000 or more not on contract goes to RFQ with 3 suppliers.",
 "when": {"and": [{"==": [{"var": "requirement.plant"}, "CHK1"]}, {">=": [{"var": "requirement.value_inr"}, 50000]}]},
 "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 3}}
```

**The app shows:**
<!-- expect -->
> New rule 5.2A 'Chakan RFQ from 50,000' after 5.2: applies when plant is 'CHK1' and requirement value is at or above 50,000; outcome: RFQ with 3 suggested suppliers

### 6b. Category

**Says:** "Calibration and testing services are always sourced by RFQ, unless on contract."

<!-- case 6b -->
<!-- insert rules after 5.2 -->
```json
{"id": "5.2B", "title": "Testing always RFQ", "clause_text": "Testing & Calibration items not on contract go to RFQ.",
 "when": {"==": [{"var": "item.category"}, "Testing & Calibration"]},
 "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 3}}
```

**The app shows:**
<!-- expect -->
> New rule 5.2B 'Testing always RFQ' after 5.2: applies when item category is 'Testing & Calibration'; outcome: RFQ with 3 suggested suppliers

### 6c. Item type

**Says:** "Services above ₹1,00,000 need an RFQ."

<!-- case 6c -->
<!-- insert rules before 5.4 -->
```json
{"id": "5.3A", "title": "Services RFQ above 1,00,000", "clause_text": "A service above 1,00,000 goes to RFQ.",
 "when": {"and": [{"==": [{"var": "item.item_type"}, "Service"]}, {">": [{"var": "requirement.value_inr"}, 100000]}]},
 "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 3}}
```

**The app shows:**
<!-- expect -->
> New rule 5.3A 'Services RFQ above 1,00,000' after 5.3: applies when item type is 'Service' and requirement value is above 1,00,000; outcome: RFQ with 3 suggested suppliers

### 6d. Department

**Says:** "IT purchases are never bought on a spot PO; they go to RFQ."

<!-- case 6d -->
<!-- insert rules before 5.4 -->
```json
{"id": "5.3A", "title": "IT never spot", "clause_text": "Requests from the IT department are not bought on spot PO; they go to RFQ.",
 "when": {"==": [{"var": "first_line.department"}, "IT"]},
 "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 3}}
```

The department of a clubbed requirement is its first line's. For "any line from IT" use
`{"some": [{"var": "lines"}, {"==": [{"var": "department"}, "IT"]}]}`.

**The app shows:**
<!-- expect -->
> New rule 5.3A 'IT never spot' after 5.3: applies when first_line.department is 'IT'; outcome: RFQ with 3 suggested suppliers

### 6e. Urgency

**Says:** "An emergency that cannot be placed as an emergency PO goes to RFQ with two suppliers, not through the
normal routes."

<!-- case 6e -->
<!-- insert rules after 5.3 -->
```json
{"id": "5.3A", "title": "Emergency fallback RFQ", "clause_text": "An emergency not placed under 5.3 goes to RFQ with 2 suppliers.",
 "when": {"==": [{"var": "derived.is_emergency"}, true]},
 "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 2}}
```

`derived.is_emergency` is "any line marked Emergency" (policy 2.3); `first_line.urgency` is the first line's only.

**The app shows:**
<!-- expect -->
> New rule 5.3A 'Emergency fallback RFQ' after 5.3: applies when it is an emergency; outcome: RFQ with 2 suggested suppliers

### 6f. Value band

**Says:** "Requirements from ₹2,00,000 up to ₹5,00,000 go to RFQ with four suppliers."

<!-- case 6f -->
<!-- insert rules before 5.5 -->
```json
{"id": "5.4A", "title": "Mid-value RFQ", "clause_text": "From 2,00,000 up to 5,00,000: RFQ with 4 suppliers.",
 "when": {"and": [{">=": [{"var": "requirement.value_inr"}, 200000]}, {"<=": [{"var": "requirement.value_inr"}, 500000]}]},
 "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 4}}
```

**The app shows:**
<!-- expect -->
> New rule 5.4A 'Mid-value RFQ' after 5.4: applies when requirement value is at or above 2,00,000 and requirement value is at or below 5,00,000; outcome: RFQ with 4 suggested suppliers

### 6g. Purchase history

**Says:** "An item not bought for more than 180 days is not bought on a spot PO; get quotes."

<!-- case 6g -->
<!-- insert rules before 5.4 -->
```json
{"id": "5.3A", "title": "Stale history RFQ", "clause_text": "An item last bought more than 180 days ago goes to RFQ.",
 "when": {">": [{"var": "history.days_since_last_po"}, 180]},
 "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 3}}
```

`history.days_since_last_po` counts from the latest PO with any supplier in the 365-day valuation window; an item
with no PO in that window has no value here, so this rule does not fire for it (it already falls to 5.5/5.6).
Other history facts: `history.po_count`, `history.active_po_count`, `history.bought_from_active`.

**The app shows:**
<!-- expect -->
> New rule 5.3A 'Stale history RFQ' after 5.3: applies when days since the last PO is above 180; outcome: RFQ with 3 suggested suppliers

### 6h. A mix

**Says:** "At Pune, non-emergency electrical spares above ₹1,00,000 go to RFP."

<!-- case 6h -->
<!-- insert rules before 5.4 -->
```json
{"id": "5.3A", "title": "Pune electrical RFP", "clause_text": "At PUN1, a non-emergency Electrical Spares requirement above 1,00,000 goes to RFP.",
 "when": {"and": [{"==": [{"var": "requirement.plant"}, "PUN1"]}, {"==": [{"var": "item.category"}, "Electrical Spares"]},
                  {"!=": [{"var": "derived.is_emergency"}, true]}, {">": [{"var": "requirement.value_inr"}, 100000]}]},
 "then": {"decision": "SOURCING_REQUEST", "route": "RFP", "supplier": "suggest", "price": "none", "suggest_count": 5}}
```

**The app shows:**
<!-- expect -->
> New rule 5.3A 'Pune electrical RFP' after 5.3: applies when plant is 'PUN1' and item category is 'Electrical Spares' and not it is an emergency and requirement value is above 1,00,000; outcome: RFP with 5 suggested suppliers

---

## 7. A rule that needs a new fact (derived fact)

**Edit:** append the fact to `"derived_facts"` (a `name` that is a plain identifier, a `description`, an `expr`),
then use it in a rule as `derived.<name>`. Derived facts are computed in order before the rules, so a fact may use
an earlier one. A missing input makes the fact empty, and a comparison on it false.

### 7a. Lead time (requirement date to the first line's need-by date)

**Says:** "If the material is needed 30 days or more after the request, it is sourced by RFQ even when small."

<!-- case 7a -->
<!-- append derived_facts -->
```json
{"name": "lead_days", "clause": "A-7", "description": "Days from the requirement date to the first line's need-by date.",
 "expr": {"date_diff_days": [{"var": "first_line.need_by_date"}, {"var": "requirement.date"}]}}
```
<!-- insert rules before 5.4 -->
```json
{"id": "5.3A", "title": "Long lead time RFQ", "clause_text": "Needed 30 days or more after the request: RFQ.",
 "when": {">=": [{"var": "derived.lead_days"}, 30]},
 "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 3}}
```

(The catalogue already has the same number as `requirement.lead_time_days`; the derived fact shows the pattern for
any date difference.)

**The app shows:**
<!-- expect -->
> New derived fact lead_days = days from requirement date to need-by date
> New rule 5.3A 'Long lead time RFQ' after 5.3: applies when lead days is at or above 30; outcome: RFQ with 3 suggested suppliers

### 7b. Price compared with the standard price

**Says:** "Where the price is more than 10% above the item's standard price, get quotes."

<!-- case 7b -->
<!-- append derived_facts -->
```json
{"name": "price_over_standard_pct", "clause": "A-8", "description": "Valuation price above the standard price, in per cent.",
 "expr": {"*": [{"/": [{"-": [{"var": "requirement.valuation_price"}, {"var": "item.standard_price"}]}, {"var": "item.standard_price"}]}, 100]}}
```
<!-- insert rules before 5.4 -->
```json
{"id": "5.3A", "title": "Price above standard RFQ", "clause_text": "Price more than 10% above the standard price: RFQ.",
 "when": {">": [{"var": "derived.price_over_standard_pct"}, 10]},
 "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": "suggest", "price": "none", "suggest_count": 3}}
```

`requirement.valuation_price` is the unit price the requirement was valued at (3.1: contract rate, latest PO, or
standard price); `requirement.valuation_source` says which.

**The app shows:**
<!-- expect -->
> New derived fact price_over_standard_pct = ((valuation price - standard price) / standard price) * 100
> New rule 5.3A 'Price above standard RFQ' after 5.3: applies when price over standard pct is above 10; outcome: RFQ with 3 suggested suppliers

---

## 8. Remove or narrow a rule

### 8a. Remove

**Says:** "Clause 5.1 (Capex goes to sourcing) is withdrawn."

<!-- case 8a -->
Delete the whole `{"id": "5.1", ...}` object from `"rules"` (and the comma before or after it):
<!-- remove rules 5.1 -->

**The app shows:**
<!-- expect -->
> Rule 5.1 removed

### 8b. Narrow

**Says:** "Emergency POs are allowed only at the Pune plant."

<!-- case 8b -->
In rule `5.3`, replace `"when"` (add the new condition to the `and` list):
<!-- set rules[5.3].when -->
```json
{"and": [{"==": [{"var": "derived.is_emergency"}, true]}, {"meets_limit": [{"var": "requirement.value_inr"}, "limits.emergency_po"]},
         {"==": [{"var": "history.bought_from_active"}, true]}, {"==": [{"var": "requirement.plant"}, "PUN1"]}]}
```

**The app shows:**
<!-- expect -->
> Rule 5.3 'Emergency PO' changed (when): now applies when it is an emergency and requirement value is at or below 5,00,000 (Emergency PO limit) and bought from an Active supplier recently and plant is 'PUN1'; outcome: EMERGENCY_PO to the 1st preferred supplier at its reference price

---

## 9. Windows and recency buckets

**Edit:** each window is `length` (a positive number), `unit` (`"calendar_days"`, `"hours"` or `"minutes"`) and
`inclusive` (true: exactly the length still counts). Change `length`; leave the other fields.

### 9a. Clubbing windows (2.2)

**Says:** "Lines raised within 21 days of each other, with need-by dates within 10 days, are combined."

<!-- case 9a -->
<!-- set parameters.clubbing.creation_window.length -->
```json
21
```
<!-- set parameters.clubbing.need_by_window.length -->
```json
10
```

**The app shows:**
<!-- expect -->
> Clubbing creation window: 14 calendar days becomes 21 calendar days
> Clubbing need by window: 7 calendar days becomes 10 calendar days

### 9b. Consolidation window (7.1)

**Says:** "Requirements for the same supplier within 48 hours share a PO."

<!-- case 9b -->
<!-- set parameters.consolidation.window.length -->
```json
48
```

**The app shows:**
<!-- expect -->
> Consolidation window: 24 hours becomes 48 hours

### 9c. History windows (365 and 548 days)

**Says:** "Valuation and the purchase-history test look back 180 days; the preferred list looks back 365 days."

`valuation_window` is 3.1(b), `purchase_window` is "bought from an Active supplier" (5.3, 5.4), `preferred_window`
is the preferred list and reference price (6.1, 6.3).

<!-- case 9c -->
<!-- set parameters.history.valuation_window.length -->
```json
180
```
<!-- set parameters.history.purchase_window.length -->
```json
180
```
<!-- set parameters.history.preferred_window.length -->
```json
365
```

**The app shows:**
<!-- expect -->
> History valuation window: 365 calendar days becomes 180 calendar days
> History purchase window: 365 calendar days becomes 180 calendar days
> History preferred window: 548 calendar days becomes 365 calendar days

### 9d. Recency buckets (6.2)

**Says:** "A PO in the last 60 days scores full recency; up to 180 days, half."

<!-- case 9d -->
Replace `"buckets"` in `parameters.ranking.recency_buckets` (older than the last bucket scores `older_score`, 0):
<!-- set parameters.ranking.recency_buckets.buckets -->
```json
[{"max_age_days": 60, "inclusive": true, "score": 1.0}, {"max_age_days": 180, "inclusive": true, "score": 0.5}]
```

**The app shows:**
<!-- expect -->
> Setting ranking.recency_buckets.buckets: [{"max_age_days": 90, "inclusive": true, "score": 1.0}, {"max_age_days": 365, "inclusive": true, "score": 0.5}] becomes [{"max_age_days": 60, "inclusive": true, "score": 1.0}, {"max_age_days": 180, "inclusive": true, "score": 0.5}]

---

## 10. Clubbing and consolidation keys

**Says:** "Only lines from the same department are combined." / "POs are consolidated per supplier and plant only."

**Edit:** `match_on` lists the fields that must be equal. Clubbing may use any PR column plus `category` and
`item_type`; consolidation may use `supplier_id`, `plant`, `route`, `decision` or any PR column.

<!-- case 10 -->
<!-- set parameters.clubbing.match_on -->
```json
["item_code", "plant", "department"]
```
<!-- set parameters.consolidation.match_on -->
```json
["supplier_id", "plant"]
```

**The app shows:**
<!-- expect -->
> Setting clubbing.match_on: ["item_code", "plant"] becomes ["item_code", "plant", "department"]
> Setting consolidation.match_on: ["supplier_id", "plant", "route"] becomes ["supplier_id", "plant"]

---

## 11. Which supplier statuses may receive a PO or be suggested

**Says:** "Inactive suppliers may be invited to quote." (Blocked suppliers: the brief penalises using them; do not
allow them unless the amendment says so in as many words.)

**Edit:** `parameters.suppliers.allowed_statuses`: five lists drawn from `Active`, `Blocked`, `Inactive`:
`receive_po`, `be_suggested`, `count_for_purchase_history`, `hold_applicable_contract`, `join_preferred_list`.

<!-- case 11 -->
<!-- set parameters.suppliers.allowed_statuses.be_suggested -->
```json
["Active", "Inactive"]
```

**The app shows:**
<!-- expect -->
> Setting suppliers.allowed_statuses.be_suggested: ["Active"] becomes ["Active", "Inactive"]

---

## 12. Ranking weights and the category top-up

**Says:** "Recency counts less: weight 3." / "Delivery performance counts twice as much as quality in the category
list."

**Edit:** `parameters.ranking.preferred_score.weights` (all five, numbers ≥ 0: `po_count`, `recency`,
`contract_held`, `on_time`, `quality`; D24) and `parameters.ranking.category_topup` (`on_time_weight`,
`quality_weight`: score = on_time_pct/100 × on_time_weight + quality_rating/5 × quality_weight). Update the `text`
next to them too.

<!-- case 12 -->
<!-- set parameters.ranking.preferred_score.weights.recency -->
```json
3
```
<!-- set parameters.ranking.category_topup.on_time_weight -->
```json
2.0
```

**The app shows:**
<!-- expect -->
> Setting ranking.category_topup.on_time_weight: 1 becomes 2
> Setting ranking.preferred_score.weights.recency: 5 becomes 3

---

## 13. Valuation price order and D2

**Says:** "Value a requirement at the latest purchase price before any contract rate." / "Purchases from blocked or
inactive suppliers no longer count for valuation."

**Edit:** `parameters.valuation.price_sources`: the order tried (from `contract_to_be_used`,
`lowest_applicable_contract_rate`, `latest_po_in_window`, `standard_price`). `include_non_active_suppliers` is D2:
`true` counts POs with any supplier for valuation, `false` only allowed statuses.

<!-- case 13 -->
<!-- set parameters.valuation.price_sources -->
```json
["latest_po_in_window", "contract_to_be_used", "lowest_applicable_contract_rate", "standard_price"]
```
<!-- set parameters.valuation.include_non_active_suppliers -->
```json
false
```

**The app shows:**
<!-- expect -->
> Setting valuation.price_sources: ["contract_to_be_used", "lowest_applicable_contract_rate", "latest_po_in_window", "standard_price"] becomes ["latest_po_in_window", "contract_to_be_used", "lowest_applicable_contract_rate", "standard_price"]
> Setting valuation.include_non_active_suppliers: true becomes false

---

## 14. Something the format cannot express

**Says:** anything that is not a decision the engine makes: "Buyers must attach three quotations", "Capex needs CFO
sign-off", a new route, a new export column, a duty to notify someone.

**Edit:** `change_summary`: one line per clause of the amendment, saying how each was handled, and for each clause
not expressed, "NOT EXPRESSED" with the reason. The reviewer sees it on the draft page, in What changes and in the
version list; it is stored with the approved version and its audit entry, so the evaluators can read it too.

<!-- case 14 meta -->
<!-- set change_summary -->
```json
"Amendment 1. Clause 1: spot limit 1,50,000 (parameters.limits.spot_po). Clause 2: NOT EXPRESSED - buyers must attach three quotations to an RFQ above 5,00,000; a process step, not a routing decision, so no decision changes."
```
<!-- set parameters.limits.spot_po -->
```json
{"value": 150000, "operator": "<", "clause": "5.4", "text": "below 1,50,000"}
```

**The app shows:**
<!-- expect -->
> Spot PO limit: below 2,00,000 becomes below 1,50,000
> Version: '5.0' becomes '5.1'
> Effective from: '2026-04-01' becomes '2026-12-01'
> Supersedes: none becomes '5.0'
> Source document: 'Corvo_Procurement_Policy.pdf, version 5.0, effective 1 April 2026' becomes 'entered by hand'
> Change summary: 'Baseline policy transcribed from the PDF. Readings of points the PDF leaves open are in DECISIONS.md (D1-D10).' becomes 'Amendment 1. Clause 1: spot limit 1,50,000 (parameters.limits.spot_po). Clause 2: NOT EXPRESSED - buyers must attach three quotations to an RFQ above 5,00,000; a process step, not a routing decision, so no decision changes.'

---

## Checklist: reviewing a draft against the amendment, clause by clause

Do this on the draft's page before **Approve**. Write the clause numbers down the side of a sheet.

1. **Every clause is accounted for.** For each clause of the amendment, find either its sentence under **What
   changes**, or its "NOT EXPRESSED" line in the change summary. A clause with neither is missing: add it.
2. **Each sentence says exactly what the clause says**: the number (1,50,000, not 15,000), the operator ("below"
   for "less than", "at or below" for "up to"), the plant or category spelled as in the data, the rule's position
   ("after 5.2"), the suggestion count.
3. **Nothing unintended.** Every sentence under What changes belongs to a clause. Allowed extras: the metadata lines
   (Version, Supersedes, Effective from, Source document, Change summary). Anything else is an accident: undo it.
4. **Effective date and label.** "Effective from: ... becomes '<the amendment's date>'", and the version label is the
   one the amendment names (or the proposed next label). An amendment with no date: do not invent one.
5. **Must be fixed before approval** is empty.
6. **Impact preview** on their batch:
   - every changed line has a requirement date **on or after** the effective date (a line before it cannot change:
     if one does, the date or the version is wrong);
   - the lines you expected to change (one per clause, picked by hand) are in the list, and lines the amendment does
     not touch are not;
   - "No decision changes: the effective date ... is after the last requirement in this batch" means Run 2 by date
     equals Run 1. That is the policy working as written (D36), not a fault.
7. **Approve**, then process the batch by requirement date (docs/thursday.md step 21).
