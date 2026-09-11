# The artifact

- **Repository:** https://github.com/yitaohou/reign-watch
- **Walkthrough (4 min):** https://www.loom.com/share/cfc7f9603f80419fa43589335b37c07a

**Reign Watch** — a Claude agent, a custom MCP server, and HubSpot, wired so that a change in a public regulation becomes one sourced, account-specific brief per affected bank, with an R-17 audit record written before anything else and a named human between the brief and any send. Code and setup are in `artifact/` and `README.md`.

## Flow

![Flow](flow.svg)

- **`regulatory-watch` skill** — runs one check cycle: diffs every watched page against its last snapshot, decides whether a change is material or noise, screens every company in the CRM in a fixed order with one reason each, and calls the brief skill once per affected account.
- **`regulatory-brief` skill** — writes the brief for one account: three sections, every sentence cited to a page fetched this cycle, section 2 from that account's own CRM record phrased as a condition, one ask, under 250 words.
- **Python** (`reign_tools.py`, `app.py`, `brief_eval.py`) — fetches, diffs and remembers; writes the R-17 record before any brief can render and refuses incomplete ones; runs the seven eval checks; schedules the agent and shows its progress. It never judges.
- **HubSpot** — the system of record. Companies carry ten `reign_*` flags (segment, gates, applicability); the agent reads them through HubSpot's MCP connector, allow-listed to read-only tools, and writes nothing back.
- **People** — the named approver opens the gate on a brief; the CEO or CRO can kill the motion. Nothing in the system sends.

## Where the constraints live

- **R-17** — `write_audit` refuses any record missing a field, with a vague purpose, or with an unresolvable principal, approver or object; `@audited` makes the brief's render code unreachable until the record is written; eval check 5 verifies independently that the record predates the brief.
- **Named human** — `approver` must resolve to a person in the directory; the dashboard enables Approve only for that person and the API refuses anyone else; Kill is visible only to `can_kill` humans.
- **Precision** — one change fans out to N accounts as N distinct briefs, each written from that account's own record and each approved separately; every account screened out is listed with its reason.
- **Reusability** — one `playbook_id`; a new regulation is a new trigger file and a playbook instance; a new product launch is the same playbook with `product` and `audience` changed and `version` bumped.

## Test mode

The watched documents rarely change, so the dashboard offers two scenarios that seed index-page baselines from Wayback Machine captures (January, April, August, September 2026) in a separate state tree and let a check replay what actually happened: scenario A surfaces SR 26-2 itself on the Fed index and produces a brief per affected account; scenario B surfaces SR 26-6 and is judged noise. Normal-mode state is untouched.
