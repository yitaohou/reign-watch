# Reign Watch

**Repository:** https://github.com/yitaohou/reign-watch
**Walkthrough (4 min):** https://www.loom.com/share/cfc7f9603f80419fa43589335b37c07a

A regulatory-trigger agent for the Reign first motion. It watches public regulatory sources, judges whether a change matters, screens the accounts in HubSpot that the change reaches, and drafts one sourced account brief per affected account — with an R-17 audit record written before anything else happens and a named human between the brief and any send.

Built for the iTmethods Week-1 Wire assignment. Two tool classes: a Claude agent running two skills over a custom MCP server, and HubSpot as the system of record via its MCP connector.

---

## What it does

```
scheduler / "Check now"
   │
   ▼  claude -p · skill: regulatory-watch
   ├─ checking    diff_source() on every watched URL → changed? added / removed lines, new links
   ├─ judging     material (obligation, scope, threshold, a new document on AI/agents/model risk)
   │              or noise (navigation, date stamps, unrelated links)?
   │      ├─ nothing changed ─────────────► no_change
   │      ├─ noise ─────────────────────► noise   (reason + raw diff kept for review; no action)
   │      └─ material ▼
   ├─ screening   companies from HubSpot → CEO exclusions → segment → four ICP gates → regulation flag
   │              → affected / not affected, one reason each; a `score` record per affected FS account
   └─ writing     emit_brief() once per affected account
                    write_audit (create)  → fails closed: no record, no brief
                    render HTML           → section 1 shared; section 2 from that account's CRM record
                    brief_eval (7 checks) → citations, length, banned phrases, source hashes, audit, send, one ask
                    handoff.json          → for Campaign Manager; approved_at: null
   ▼
dashboard   Regulations → Checks → one Check (verdict · Briefs · Companies screened) → Brief
            Approve: the named approver only · Kill: CEO / CRO only · nothing is ever sent
```

Python fetches, diffs, records and blocks. The agent reads, judges, screens and writes. A person approves or kills.

---

## Repository layout

```
artifact/
  mcp/reign_tools.py        six tools, served over MCP (stdio) or run as a CLI
                              fetch_source · diff_source · lookup · write_audit · check_kill · emit_brief
  skill/regulatory-brief/   how a trigger becomes a three-section, fully cited brief
  skill/regulatory-watch/   one check cycle: diff → judge → screen → brief per account → JSON
  eval/brief_eval.py        seven mechanical checks a brief must pass before it gets a hand-off
  eval/banned_phrases.txt
  server/app.py             FastAPI: scheduler, headless-agent runner, API, test mode, approvals
  server/dashboard.html     four-level UI + Audit page + identity switch + test mode
  data/icp.json             machine-readable ICP: gates, exclusions, segments (invented fields flagged)
  data/directory.json       named humans (who may approve, who may kill), agent ids, mock accounts
  triggers/*.json           per regulation: content URLs, index URLs, applies_to (segments + required flag)
  playbooks/*.json          Campaign Manager playbook instances, one per trigger
  test/fixtures/*.json      Wayback Machine link sets used as historical baselines in test mode
packet/                     the assignment packet, verbatim
reconciled-docs/            ICP, Campaign Manager schema and R-17 as reconciled, with reasons
deliverables/               01 artifact summary · 02 process log · 03 what I did not know · 04 what I would not ship
```

Not in the repository (`.gitignore`): `artifact/runs/` and `artifact/runs-test/` — runtime state (snapshots, check records, audit log, briefs, cache). They are created on first use. A fresh clone's first check is a `baseline`, not a comparison.

---

## Setup

**1. Python**

```bash
python3 -m venv artifact/mcp/.venv
artifact/mcp/.venv/bin/pip install pypdf mcp fastapi 'uvicorn[standard]'
```

**2. Claude Code CLI** — the server runs the agent as `claude -p`. Install Claude Code and be logged in on the machine that runs the server. Verify:

```bash
claude --version
```

**3. HubSpot** — the system of record. Connect HubSpot to your Claude account (claude.ai → connectors) and create these custom **company** properties. Values are yours to set; the agent only reads.

| Property (internal name) | Type | Meaning |
|---|---|---|
| `reign_account_id` | text | stable id, e.g. `acct-dsib-001` — becomes the R-17 `object` |
| `reign_segment` | select | `D-SIB / capital markets` · `Regional bank` · `Global biopharma quality` · `Defense supplier` · `Semiconductor` · `Mid-market SaaS` · `Insurance / asset manager` · `Fintech` |
| `reign_regulated_fs` | yes/no | regulated financial services → R-17 audit required |
| `reign_employees_5k_plus` | yes/no | ICP gate |
| `reign_agents_in_prod` | yes/no | ICP gate: agents in production or imminent |
| `reign_risk_committee` | yes/no | ICP gate: without one the briefing is wasted |
| `reign_us_assets_over_30b` | yes/no | SR 26-2 applicability |
| `reign_eu_entity` | yes/no | DORA applicability |
| `reign_runs_forge` | yes/no | context for section 2 |
| `reign_known_facts` | text | notes the brief may lean on — treated as *our records*, never stated as the bank's facts |

One contact per company (the risk-lane recipient, e.g. Chief Audit Executive). During development every contact email should point at your own inbox.

Without HubSpot connected, checking and judging still run; screening reports that no HubSpot tools are available.

**4. Run**

```bash
artifact/mcp/.venv/bin/python artifact/server/app.py
# → http://localhost:8787
```

---

## Using it

- **Regulations** — one row per trigger. Toggle a watch, set the interval (applies on *Apply*), press *Check now* or *Check all*. A watch that has never run waits for a manual first check; the schedule starts from it.
- **Acting as** — pick who you are. *Approve* is enabled only for the brief's named approver; *Kill motion* appears only for people with `can_kill` in `directory.json`. Both are enforced server-side as well.
- **Checks** — every cycle for that regulation: result, the agent's one-line judgment, how many companies were screened, how many briefs.
- **A check** — the sources examined (links, what changed), the raw diffs the agent saw, every company screened with its verdict and reason, and the briefs produced with their approval state and R-17 record.
- **Audit** — briefs awaiting review and reviewed; click any row for the R-17 record.

Nothing in this system sends. Approval fills `approved_at`; sending is Campaign Manager's action and needs its own R-17 `message` record (`handoff.json` → `send_requires`).

---

## Test mode

The documents being watched rarely change, so test mode replays changes that already happened. *Test mode…* at the bottom of the Regulations page offers two scenarios; entering one builds a separate state tree (`artifact/runs-test/`), seeds index-page baselines from Wayback Machine captures stored in `test/fixtures/`, and turns the scheduler off. A check then compares today's live pages against a months-old baseline.

| Scenario | Baselines | Expected |
|---|---|---|
| A | EIOPA DORA page 2026-01-08 · Fed SR letters index 2026-04-05 | SR-26-2: a brief per affected account (SR 26-2 itself appears on the index). DORA: noise |
| B | EIOPA DORA page 2026-08-23 · Fed 2026 index 2026-09-06 | SR-26-2: noise (SR 26-6, unrelated). DORA: no change |

Normal-mode state is untouched. *Exit test mode* switches back.

---

## Adding a regulation

1. `artifact/triggers/<id>.json` — `sources` (content URLs the brief may cite), `watch_index` (index pages whose new links matter), `applies_to` (segments and the CRM flag that turns the regulation on).
2. `artifact/playbooks/<segment>-<id>.json` — copy an existing instance; change `trigger.id` and `audit.purpose`.
3. It appears on the dashboard on the next refresh. First check is manual.

---

## Constraints this system is built around

- **R-17 (prospect-touch audit, FS).** Any agent action that creates, updates, enriches, scores or messages an FS account writes a record first — `actor`, `principal`, `action`, `object`, `purpose`, `sources`, `send` — or the action does not happen. `write_audit` fails closed; `emit_brief` cannot render until it returns; the eval independently checks the record predates the brief.
- **A named human before anything sends.** `approver` must resolve to a person in the directory. `send` is hard-coded false in this artifact.
- **Precision, not spray.** One regulation change fans out to *N* accounts as *N* distinct briefs — section 2 is written from each account's own record — each with its own approval. Every account screened out is listed with its reason, so a filter mistake is visible.
- **The agent judges; the code remembers and blocks.** Change detection is a hash; materiality is the agent's call; the order audit → render → eval → hand-off is Python's.

---

## Deliverables

- `deliverables/01-artifact.md` — what the artifact is for, its inputs and outputs, the flow, where each constraint lives
- `deliverables/02-process-log.md` — what was tried, what failed, what was learned, what three more hours would go to, with real skill and tool snippets
- `deliverables/03-what-i-did-not-know.md`
- `deliverables/04-what-i-would-not-ship.md`
