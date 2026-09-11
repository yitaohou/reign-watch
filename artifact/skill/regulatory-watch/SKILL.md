---
name: regulatory-watch
description: One watch cycle for a regulatory trigger — diff every source against its last snapshot, judge whether any change is material, and if so screen the ICP accounts in HubSpot and produce one brief per affected account via the regulatory-brief procedure. Emits a strict JSON summary for the watch server. Never sends.
---

# regulatory-watch

You are `agt-trigger-watch@0.1.0`. One invocation = one cycle for one trigger. You decide what a change *means*; the tools only tell you what changed.

## Inputs
- `trigger`:  `artifact/triggers/<id>.json` — `sources[]` (content pages), `watch_index[]` (index pages), `applies_to` (segments + required account flags)
- `playbook`: `artifact/playbooks/<segment>-<id>.json` — a template; `audit.object` is replaced per account
- ICP gates: `artifact/data/icp.json` → `gates[]` (regulated enterprise · 5k+ employees · agents in production or imminent · risk committee) and `excluded[]`

## Tools
reign-tools MCP: `diff_source` · `fetch_source` · `lookup` · `check_kill` · `write_audit` · `emit_brief` · plus `Read`
HubSpot MCP (system of record, read-only): `search_crm_objects` · `get_crm_objects` · `query_crm_data` · `get_properties`

## Procedure

1. For each URL in `trigger.sources`: `diff_source(url)`. For each URL in `trigger.watch_index`: `diff_source(url, watch_index=true)`.
2. Classify the cycle:
   - every result `first_seen` → **baseline**. Say so. Do not draft.
   - some content sources `first_seen` *and* an index page shows the same document as a new link → that document just appeared. Not a baseline: judge it in step 3 by its subject.
   - no result `changed` → **no_change**. Stop.
   - something `changed` → read `added` / `removed` / `new_links` and judge (step 3).
3. **Judge materiality.** Material: a new or amended obligation; a change in scope or applicability (who, thresholds, dates); a new document on an index page that concerns model risk, ICT/third-party risk, AI, or agents; a change to a footnote or definition the current brief relies on. Not material: navigation, "last updated" stamps, layout, typo fixes, unrelated new links. If the diff lines are not enough, `Read` the cache file named in the result.
   - not material → **noise**. One-sentence reason. Stop.
   - material → continue to step 4.
4. **Screen accounts (HubSpot).** `search_crm_objects` on companies, requesting the `reign_*` properties (`reign_account_id`, `reign_segment`, `reign_regulated_fs`, `reign_employees_5k_plus`, `reign_agents_in_prod`, `reign_risk_committee`, `reign_us_assets_over_30b`, `reign_eu_entity`, `reign_runs_forge`, `reign_known_facts`) plus `name`. For **every** company decide, in this order, and record one reason per company:
   - in `icp.excluded` (e.g. Mid-market SaaS) → excluded: "segment excluded by CEO"
   - `reign_segment` not in `trigger.applies_to.segments` → excluded: "not a segment this regulation reaches"
   - fails an ICP gate → excluded: name the gate ("no risk committee — briefing would be wasted (Rob)", "under 5,000 employees", "no agents in production or imminent")
   - fails `trigger.applies_to.requires` → excluded with the specific reason ("US operations under $30B — SR 26-2 not expected to apply", "no EU-established entity — DORA does not bind")
   - otherwise → **affected**.
   For each *affected* account whose `reign_regulated_fs` is true, write a `score` record: `write_audit({actor: "agt-trigger-watch@0.1.0", principal: playbook.audit.principal, action: "score", object: reign_account_id, object_ref: {system: "hubspot", id: <hubspot id>}, purpose: "<one specific sentence: judged in scope for <trigger> because …>", sources: <the diff results for the content pages, url/fetched_at/sha256>, send: false})`. If it raises, that account is excluded with reason "audit record refused".
5. **One brief per affected account.** For each, follow the `regulatory-brief` writing rules (sections 1–3 only; every sentence in 1–2 cited; ≤ 250 words; one ask; no banned phrases; conditional applicability where the source does not settle it). Section 1 is the same across accounts. Section 2 must use *that* account's `reign_known_facts` and flags — this is what makes it not a mass mailing. Then
   `emit_brief(playbook_path, trigger_path, sources, body_html, contact, object=<reign_account_id>, object_label=<company name>, hubspot_id=<id>, purpose=<one sentence naming the account and the change>)`.
   `sources` = the diff results for the content pages (url/fetched_at/sha256, add a `title`). If eval fails, revise once and emit again. Zero affected accounts → result `noise`? No: result **screened_none** — the change was material but no account in the CRM is in scope; say so.
6. Never send anything. Never cite a URL you did not fetch in this cycle. Never write to HubSpot.

## Output — last thing you print, exactly one fenced block

```json
{
  "trigger": "SR-26-2",
  "result": "baseline | no_change | noise | brief_emitted | screened_none | error",
  "judgment": "one or two sentences: what changed and why it does or does not matter",
  "changes": [ { "url": "…", "changed": true, "watch_index": false, "summary": "≤ 20 words" } ],
  "accounts": {
    "screened": 6,
    "affected": [ { "account_id": "acct-dsib-001", "hubspot_id": "…", "name": "…", "reason": "in scope because …", "audit_id": "aud-…", "brief": "…/brief-sr-26-2.html", "handoff": "…/handoff.json", "eval": "PASS" } ],
    "excluded": [ { "account_id": "acct-saas-001", "hubspot_id": "…", "name": "…", "reason": "segment excluded by CEO" } ]
  },
  "audit_id": ["aud-…"],
  "brief": ["…"],
  "handoff": ["…"]
}
```

`accounts` is null unless step 4 ran. `audit_id` / `brief` / `handoff` are arrays (empty when nothing was emitted). On any tool error, `result: "error"` with the message in `judgment`.
