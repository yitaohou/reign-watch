# Assignment: Week-1 Wire

Growth Engineer (AI-Native) · iTmethods

Time box: 3 hours from the moment you open the packet. Do not polish after.

This is not a campaign brief and not a slide exercise. We want to see how you decompose a messy problem, what you go learn, and whether you can ship a real agentic artifact under time.

## What we are testing

- Problem-solving process (what you cut, what you sequenced, what you refused)
- Ability to learn something you did not already know
- Curiosity (what you went looking for vs what you assumed)
- AI depth (agents, skills, MCP, evals — not "I asked ChatGPT")
- Tool range across Clay-class, HubSpot, ZoomInfo or a comparable stack, plus whatever else you reach for

## The situation

Reign Ops, Reign Factory, Reign Gateway, and Reign Assurance are the product line. iTmethods is the company. A first motion is going to a D-SIB bank, a global biopharma quality org, and a defense supplier. You are the operator. CEO and CRO want it live, not a plan. You have three hours.

## The packet (messy on purpose)

You will get a folder with:

1. **CEO notes** — a dump. It contradicts itself. Reconcile it. Do not blindly execute every sentence.
2. **A thin ICP sketch** — missing fields. Encode a living ICP anyway. Say what you invented and why.
3. **A Reign constraint** — a one-page rule: every agent action that touches a prospect in financial services must leave an audit trail (who/what/why, and a named human approver for anything that sends). Learn it and obey it. If your motion cannot satisfy it, say so and redesign.
4. **A stub for an internal surface** — "Campaign Manager" accepts a JSON playbook (`audience`, `trigger`, `channel`, `approval`, `kill_criteria`). Schema is incomplete. Infer the rest. Document the guesses.

You may use Claude, Cursor, Clay, HubSpot, ZoomInfo, n8n, your own MCP servers, and anything else. Say what you used. If you do not have Clay or HubSpot, substitute and say what you would wire on day one.

## What to ship

Four things. Nothing else.

1. **A working artifact** (pick one, go deep, do not spray):
   - a Clay workbook or table that enriches/tiers the ICPs and writes a governed brief, or
   - a HubSpot workflow (export or screenshots + logic) that does MQL→SQL handoff with a human approval gate, or
   - a Claude skill / MCP / small agent that turns a regulatory trigger (EU AI Act, SR 26-2, DORA, or FDA PCCP) into a short, non-slop account brief with sources
2. **A process log** (one page). What you tried, what failed, what you learned, what you would do with another three hours. Include 2–3 actual prompts, skill snippets, or tool configs. Not a narrative of how smart you are.
3. **One thing you did not know when you started** and how you got dangerous in it during the three hours. Be specific.
4. **What you would not ship** and why. Especially anything that would embarrass us in front of a bank, hospital, or defense buyer.

Optional: a 4-minute loom walking the artifact. No voiceover recap of your resume.

## Rules

- Clock starts when you open the packet. Stop at 3:00. Incomplete and honest beats complete and generic.
- You must use an agent to do part of the work, and you must show the scaffolding (prompt, skill, tool calls, or eval). A chat screenshot of "write me a GTM plan" is a fail.
- You must touch at least two tool classes (example: Clay + Claude, or HubSpot + a custom MCP). One-tool tours fail.
- Do not send a deck. Do not send a 12-page strategy memo.
- If you get stuck, write the stuck and the next experiment. That is signal.

## Knockouts

AI-curious only, marketing-only plan, high-volume slop outbound, no artifact, no evidence of learning, ignored the Reign constraint.
