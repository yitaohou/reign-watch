# Campaign Manager — reconciled schema

Working copy. Edits so far are listed under **Decisions**; `// GUESS` marks anything not traceable to the packet. Original at `packet/assignment-packet-campaign-manager.md`.

```jsonc
{
  "playbook_id": "string",
  "version": "1.0.0",                                   // GUESS: semver
  "product": "reign | forge",
  "audience": { "icp_id": "string", "segment": "string" },
  "trigger": { "type": "regulatory | event | manual", "id": "string" },   // one trigger per playbook; the bank = two playbooks (SR-26-2, DORA)
  "channel": "briefing | sequence | slack | unknown",   // briefing = Executive Assurance Briefing (CEO notes); every channel counts as a send → approver required; unknown is blocked
  "approval": {
    "approver": "hum-xxx",                              // named human, id from the directory below
    "approved_at": "ISO-8601 | null"                    // null = not approved yet → send is blocked
  },
  "kill_criteria": [
    { "id": "audit_write_failed", "when": "audit record could not be written",                          "action": "abort", "scope": "fs_only" },   // R-17 required for FS only; other segments do not trip this
    { "id": "channel_unknown",    "when": "channel = unknown, approver cannot be determined",             "action": "block_send" },
    { "id": "approver_missing",   "when": "send = true and approver is empty",                            "action": "block_send" },
    { "id": "source_stale",       "when": "a cited URL no longer resolves, or its content changed since fetched_at", "action": "block_send" },
    { "id": "briefing_not_booked","when": "segment = D-SIB and channel != briefing and no Executive Assurance Briefing on the calendar", "action": "block_send", "unless": "trigger.type = regulatory" },   // CEO: no bank outbound until the briefing is booked; regulatory trigger is the exception
    { "id": "manual_kill",        "by": ["hum-001", "hum-002"],                                                    "action": "abort" }   // CEO: "I will kill the motion"; stub: CRO stops a motion
  ],
  "audit": {                                            // R-17 fields
    "actor": "agt-xxx@0.1.0",                           // agent id + version
    "principal": "hum-xxx",                             // named human who authorized this class of action
    "action": "create | update | enrich | score | message",   // R-17: the five recorded action types
    "object": "acct-xxx | cont-xxx",
    "purpose": "one sentence, specific",
    "sources": [ { "url": "string", "fetched_at": "ISO-8601", "sha256": "string" } ],   // GUESS: timestamp + hash so source_stale is decidable
    "send": false,
    "approver": "hum-xxx | null"                        // required when send = true; mirrors approval.approver
  }
}
```

## Decisions

- `version` added — semver is a guess.
- `approval` — an approver id (must resolve to a human in the directory) and an approval timestamp. Null timestamp = not approved = blocked.
- `audit` — the seven R-17 fields verbatim; `action` is an enum of the five action types R-17 says must be recorded. `sources` entries carry `fetched_at` and a content hash so "the basis no longer holds" is checkable, not a judgment call.
- `trigger` — one per playbook. Stub asked whether many; answer is no. One trigger = one playbook instance: the bank runs two, identical except `trigger.id` (`SR-26-2`, `DORA`), so the two briefs and their kills stay separate.
- `channel: briefing` — means the Executive Assurance Briefing named in the CEO notes.
- Every channel counts as a send — briefing, sequence, slack alike — so `approval.approver` is always required and `audit.send` is true whenever a channel is used. `unknown` is blocked by `channel_unknown`.
- `kill_criteria` — six rules:
  - **audit_write_failed** → abort the whole action. R-17: if the record cannot be written, the action does not happen. `scope: fs_only` — fires for the D-SIB bank; biopharma and defense run without audit and do not trip it.
  - **channel_unknown** → approver cannot be determined, block the send.
  - **approver_missing** → `send` is true but `approver` is empty.
  - **source_stale** → a URL the brief cites no longer opens, or its content changed. Added because timestamped sources make this decidable.
  - **briefing_not_booked** → D-SIB, any channel other than the briefing itself, and no Executive Assurance Briefing on the calendar → block. `unless: trigger.type = regulatory` is the CEO's exception (a CAE-forwardable brief may go out on SR 26-2 / DORA).
  - **manual_kill** → CEO or CRO can abort the motion by hand. Stub says kill_criteria is how CRO stops a motion; the four automatic rules alone had no human on the switch.

---

## Mock directory (模拟数据，供 approval / audit 字段引用)

Paul is the only real name in the packet. Rob appears by first name only — surname invented. Everyone else is a placeholder.

### Humans — can be `owner`, `principal`, `approver`

| id | name | role | notes |
|---|---|---|---|
| `hum-001` | Paul Goldman | CEO | from packet |
| `hum-002` | Dana Whitfield | CRO | mock — owns kill switch |
| `hum-003` | Rob Tessier | Head of Sales, Reign | first name from packet, surname mock |
| `hum-004` | Priya Raman | Compliance Lead | mock — R-17 principal for FS |
| `hum-005` | Marcus Obi | AE, D-SIB account | mock |
| `hum-006` | Yitao Hou | Growth Engineer (operator) | runs the agents |

### Agents — `actor` = id + version

| id | version | does |
|---|---|---|
| `agt-enrich` | `0.1.0` | Clay enrichment, ICP gating |
| `agt-trigger-watch` | `0.1.0` | watches SR 26-2 / DORA / FDA PCCP sources |
| `agt-brief-writer` | `0.1.0` | drafts the account brief from a trigger |

### Prospects — `object` (mock ids, real names withheld)

| id | type | segment | label |
|---|---|---|---|
| `acct-dsib-001` | account | D-SIB / capital markets | "the Canadian bank on Forge" |
| `cont-dsib-001` | contact | D-SIB | CAE at acct-dsib-001 |
| `cont-dsib-002` | contact | D-SIB | Head of Platform Eng at acct-dsib-001 |
| `acct-pharma-001` | account | Global biopharma quality | asked about FDA PCCP |
| `cont-pharma-001` | contact | Biopharma | VP Quality / RA at acct-pharma-001 |
| `acct-def-001` | account | Defense supplier | Forge-first |
