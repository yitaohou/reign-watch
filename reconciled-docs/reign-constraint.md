# R-17 — Prospect-touch audit

**Rule R-17 — Prospect-touch audit (financial services)**

Any agent action that creates, updates, enriches, scores, or messages a person or account in financial services must write an audit record before the action is considered complete.

Required fields:

- `actor` — agent id + version
- `principal` — named human who authorized this class of action
- `action` — what was done
- `object` — account or contact id
- `purpose` — one sentence, specific, not "engagement"
- `sources` — URLs or system ids used
- `send` — true/false. If true, `approver` must be a named human and the send must be blockable.

If the record cannot be written, the action does not happen.

Non-FS segments: recommended, not required, for this exercise. FS: required.

If your favorite tool cannot do this, you must wrap it or you must not send.

---

## Reconciliation

Rule text above is unchanged. Decisions on how it is applied to the first motion:

- **Scope stays FS-only.** Required for the D-SIB bank. Biopharma quality and defense supplier may run without audit records, as the rule allows for non-FS.
- **Order: record first, then action.** The rule's two sentences ("before the action is considered complete" / "if the record cannot be written, the action does not happen") are read strictly — the record is written before the action starts; a failed write means the action never runs. This is what `kill_criteria.audit_write_failed → abort` encodes.
- **`action` is an enum, not free text.** The rule names five recordable action types — create, update, enrich, score, message — so `audit.action` takes exactly those values.
- **Enrichment tooling is out of scope for this exercise.** Clay / ZoomInfo cannot write R-17 records natively; the rule says wrap or do not send. Not built here.
- **The CEO's regulatory-trigger exception is not an R-17 exception.** It relaxes *when* outbound to the bank may start, not the audit rule. A brief forwarded to a CAE still needs a named approver and must be blockable.
- **Create and message are two records.** Generating the brief is a `create` action (`send: false`); forwarding it to a person is a `message` action (`send: true`, named approver, blockable) and needs its own record with the *contact* as `object`. The artifact writes the first; `handoff.json` carries `send_requires` describing the second, which belongs to Campaign Manager.
