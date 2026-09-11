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
