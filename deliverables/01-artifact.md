# The artifact

- **Repository:** https://github.com/yitaohou/reign-watch
- **Walkthrough (4 min):** https://www.loom.com/share/cfc7f9603f80419fa43589335b37c07a

**Reign Watch** — a Claude agent, a custom MCP server, and HubSpot, wired so that a change in a public regulation becomes one sourced, account-specific brief per affected bank, with an R-17 audit record written before anything else and a named human between the brief and any send. Code and setup are in `artifact/` and `README.md`.

## Flow

```
scheduler tick / "Check now"
  |
  v   claude -p  ·  skill: regulatory-watch
  |   tools: reign-tools MCP  +  HubSpot MCP (read-only)
  |
  +-- checking    diff_source() per URL
  |               fetch -> extract text or links -> hash -> compare to last snapshot
  |               -> changed?  added/removed lines · new links · first_seen
  |
  +-- judging     the agent reads the diff
  |     all first_seen ......... baseline      snapshot stored, nothing drafted
  |     nothing changed ........ no_change
  |     not material ........... noise         reason + raw diff kept; no action
  |     material ............... continue
  |
  +-- screening   companies from HubSpot, each one in this order:
  |               CEO exclusion -> segment not reached -> fails an ICP gate
  |               -> fails the regulation's flag -> otherwise AFFECTED
  |               one reason per company; a `score` record per affected FS account
  |
  +-- writing     emit_brief() once per affected account
                  write_audit (create)   fails closed: no record, no brief
                  render                 section 1 shared · section 2 from that
                                         account's record · one ask
                  brief_eval (7 checks)  citations · <=250 words · banned phrases
                                         · source hashes · audit precedes brief
                                         · send=false · one ask
                  handoff.json           only on PASS
  |
  v
dashboard       live phase while running -> result when done
                -> briefs wait for the named approver
```

### Who does what

| Part | Responsibility |
|---|---|
| **Server** (`server/app.py`) | Decides *when* a check runs and for which regulation; starts the agent as a headless `claude -p`; reads its event stream to show the live phase; records each cycle; serves the dashboard and the approval / kill API. Makes no judgment. |
| **Tools** (`mcp/reign_tools.py`) | The only code that touches the outside or the disk: fetch a page, diff it against the last snapshot, look up a person or account, write an R-17 record, evaluate kill criteria, turn a brief into a file. `write_audit` refuses incomplete records; `emit_brief` cannot render before the record exists. |
| **Watch skill** (`skill/regulatory-watch`) | The agent's procedure for one cycle: which URLs to diff, how to classify the cycle, the materiality test, the screening order, when to call the brief skill, the JSON it must end with. |
| **Brief skill** (`skill/regulatory-brief`) | The writing rules: three sections, every sentence cited to a fetched source, the account's CRM record only and phrased as a condition, one ask, no banned phrases, 250 words. |
| **Eval** (`eval/brief_eval.py`) | Seven mechanical checks run inside `emit_brief`; a failing brief is renamed `.FAILED.html` and gets no hand-off. |
| **HubSpot** | System of record. Companies and their `reign_*` flags are read during screening; the agent never writes to it. |
| **Dashboard** (`server/dashboard.html`) | Regulations → Checks → one Check → Brief; Audit page; who you are acting as; Approve (named approver only); Kill (CEO / CRO only); test mode. |
| **Named humans** (`data/directory.json`) | Approve a brief; kill the motion. Nothing else in the system can do either. |

Python fetches, diffs, records and blocks. The agent reads, judges, screens and writes. A person approves or kills.

## Where the constraints live

- **R-17** — `write_audit` refuses any record missing a field, with a vague purpose, or with an unresolvable principal, approver or object; `@audited` makes the brief's render code unreachable until the record is written; eval check 5 verifies independently that the record predates the brief.
- **Named human** — `approver` must resolve to a person in the directory; the dashboard enables Approve only for that person and the API refuses anyone else; Kill is visible only to `can_kill` humans.
- **Precision** — one change fans out to N accounts as N distinct briefs, each written from that account's own record and each approved separately; every account screened out is listed with its reason.
- **Reusability** — one `playbook_id`; a new regulation is a new trigger file and a playbook instance; a new product launch is the same playbook with `product` and `audience` changed and `version` bumped.

## Test mode

The watched documents rarely change, so the dashboard offers two scenarios that seed index-page baselines from Wayback Machine captures (January, April, August, September 2026) in a separate state tree and let a check replay what actually happened: scenario A surfaces SR 26-2 itself on the Fed index and produces a brief per affected account; scenario B surfaces SR 26-6 and is judged noise. Normal-mode state is untouched.
