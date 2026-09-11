#!/usr/bin/env python3
"""
reign-server — runs the watch loop and serves the dashboard.

  artifact/mcp/.venv/bin/python artifact/server/app.py        → http://localhost:8787

Every cycle it invokes the *agent* (claude -p, headless, with the reign-tools MCP) on each enabled watch.
The agent runs the regulatory-watch skill: diff → judge → maybe brief. The server only schedules, records, and displays.

Two modes, two disjoint state trees:
  normal  artifact/runs/        the real motion; scheduler runs
  test    artifact/runs-test/   seeded from Wayback fixtures so a check replays a real past change; scheduler off
Kill switch: <runs>/kill.json (CEO / CRO only).
"""
import datetime, json, os, pathlib, re, shutil, subprocess, sys, threading, time
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent                       # artifact/
PROJECT = ROOT.parent                    # week1-wire/
SKILL = ROOT / "skill" / "regulatory-watch" / "SKILL.md"
BRIEF_RULES = ROOT / "skill" / "regulatory-brief" / "SKILL.md"
FIXTURES = ROOT / "test" / "fixtures"
CLAUDE = shutil.which("claude") or str(pathlib.Path.home() / ".local/bin/claude")
ALLOWED = ["mcp__reign-tools__diff_source", "mcp__reign-tools__fetch_source", "mcp__reign-tools__lookup",
           "mcp__reign-tools__check_kill", "mcp__reign-tools__emit_brief", "mcp__reign-tools__write_audit", "Read",
           # HubSpot is the system of record (CEO note). Read-only tools only; the agent never writes to the CRM.
           "mcp__claude_ai_HubSpot__search_crm_objects", "mcp__claude_ai_HubSpot__get_crm_objects",
           "mcp__claude_ai_HubSpot__query_crm_data", "mcp__claude_ai_HubSpot__get_properties",
           "mcp__claude_ai_HubSpot__search_properties", "mcp__claude_ai_HubSpot__tool_guidance"]
RUN_LOCKS: dict = {}                     # trigger_id -> Lock; watches run in parallel, the same watch never overlaps
CFG_LOCK = threading.Lock()
RUNNING: dict = {}                       # trigger_id -> started_at while a cycle is in flight
MODE: dict = {"test": None}              # None = normal; else the active scenario dict

sys.path.insert(0, str(ROOT / "mcp"))
import reign_tools as rt  # noqa: E402  (used for lookup/directory; its RUNS is per-process, we pass ours via env)

EIOPA = "https://www.eiopa.europa.eu/digital-operational-resilience-act-dora_en"
FED_MAIN = "https://www.federalreserve.gov/supervisionreg/srletters/srletters.htm"
FED_2026 = "https://www.federalreserve.gov/supervisionreg/srletters/2026.htm"
SCENARIOS = {
    "A": {"id": "A", "label": "DORA 2026-01-08 · SR 2026-04-05",
          "expect": "SR-26-2: a brief — SR 26-2 itself appears on the Fed main index (SR 26-3…26-6 alongside it as noise). DORA: noise — three non-substantive links added since January.",
          "seeds": {EIOPA + "#index": "eiopa-2026-01-08", FED_MAIN + "#index": "fed-srletters-2026-04-05"},
          "drop": ["https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm",
                   "https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf",
                   FED_2026, FED_2026 + "#index"]},   # on Apr 5 none of these existed yet
    "B": {"id": "B", "label": "DORA 2026-08-23 · SR 2026-09-06",
          "expect": "SR-26-2: noise — SR 26-6 (digital credentials / CIP FAQ) appears on the 2026 index. DORA: no change.",
          "seeds": {EIOPA + "#index": "eiopa-2026-08-23", FED_2026 + "#index": "fed-2026-2026-09-06"}},
}


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- paths (mode-dependent)
def runs_dir() -> pathlib.Path:
    return ROOT / ("runs-test" if MODE["test"] else "runs")


def P() -> SimpleNamespace:
    r = runs_dir()
    return SimpleNamespace(RUNS=r, WATCH=r / "watch", CFG=r / "watch" / "config.json", ACT=r / "watch" / "activity.jsonl",
                           DIFFS=r / "watch" / "diffs.jsonl", STATE=r / "watch" / "state.json", KILL=r / "kill.json",
                           AUDIT=r / "audit.jsonl", CACHE=r / "cache")


# ---------------------------------------------------------------- state
def triggers() -> list:
    out = []
    for p in sorted((ROOT / "triggers").glob("*.json")):
        t = json.loads(p.read_text()); t["_path"] = str(p.relative_to(PROJECT))
        pb = next((q for q in (ROOT / "playbooks").glob("*.json")
                   if json.loads(q.read_text())["trigger"]["id"] == t["id"]), None)
        t["_playbook"] = str(pb.relative_to(PROJECT)) if pb else None
        out.append(t)
    return out


def load_cfg() -> dict:
    p = P()
    cfg = json.loads(p.CFG.read_text()) if p.CFG.exists() else {}
    cfg.setdefault("interval_hours", 24); cfg.setdefault("watches", {})
    for t in triggers():
        cfg["watches"].setdefault(t["id"], {"enabled": True, "last_run": None})
    return cfg


def save_cfg(cfg: dict):
    p = P(); p.WATCH.mkdir(parents=True, exist_ok=True); p.CFG.write_text(json.dumps(cfg, indent=2))


def killed() -> dict | None:
    k = P().KILL
    return json.loads(k.read_text()) if k.exists() else None


def activity(trigger_id: str | None = None) -> list:
    a = P().ACT
    if not a.exists():
        return []
    rows = [json.loads(l) for l in a.read_text().splitlines() if l.strip()]
    return [r for r in rows if trigger_id is None or r["trigger"] == trigger_id]


def record(entry: dict):
    p = P(); p.WATCH.mkdir(parents=True, exist_ok=True)
    with p.ACT.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def audit_rows() -> list:
    a = P().AUDIT
    if not a.exists():
        return []
    return list(reversed([json.loads(l) for l in a.read_text().splitlines() if l.strip()]))


# ---------------------------------------------------------------- the agent call
def mcp_config_path() -> pathlib.Path:
    """Absolute-path MCP config for the headless run, carrying the runs dir so the tools write to the right tree.
    Passed with --strict-mcp-config so the agent sees exactly one server."""
    p = P(); p.WATCH.mkdir(parents=True, exist_ok=True)
    f = p.WATCH / "mcp.json"
    f.write_text(json.dumps({"mcpServers": {"reign-tools": {
        "command": str(ROOT / "mcp" / ".venv" / "bin" / "python"),
        "args": [str(ROOT / "mcp" / "reign_tools.py"), "serve"],
        "env": {"REIGN_RUNS_DIR": str(p.RUNS)}}}}, indent=2))
    return f


def build_prompt(t: dict) -> str:
    return (f"Follow this skill exactly. It is the regulatory-watch skill.\n\n{SKILL.read_text()}\n\n"
            f"--- The regulatory-brief writing rules referenced above ---\n{BRIEF_RULES.read_text()}\n\n"
            f"Inputs for this cycle:\n- trigger: {t['_path']}\n- playbook: {t['_playbook']}\n"
            f"- contact: Chief Audit Executive\n\nBegin. End with the single fenced JSON block.")


def parse_summary(text: str) -> dict | None:
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S) or re.findall(r"(\{[^{}]*\"result\"[^{}]*\})", text, re.S)
    for b in reversed(blocks):
        try:
            return json.loads(b)
        except json.JSONDecodeError:
            continue
    return None


PHASES = {  # tool name fragment → (phase, label)
    "diff_source": ("checking", "checking"), "fetch_source": ("checking", "checking"),
    "claude_ai_HubSpot": ("screening", "screening HubSpot"),
    "write_audit": ("screening", "screening"),
    "emit_brief": ("writing", "writing brief"),
}


def _set_phase(trigger_id: str, tool: str, inp: dict):
    st = RUNNING.get(trigger_id)
    if not st:
        return
    for frag, (phase, label) in PHASES.items():
        if frag in tool:
            st["calls"][phase] = st["calls"].get(phase, 0) + 1
            detail = ""
            if phase == "checking":
                detail = f"{st['calls'][phase]} source{'s' if st['calls'][phase] > 1 else ''}"
            elif phase == "screening" and "HubSpot" in tool:
                detail = tool.split("__")[-1].replace("_", " ")
            elif phase == "writing":
                detail = inp.get("object_label") or inp.get("object") or ""
            st.update(phase=phase, label=label, detail=detail)
            return


def run_watch(trigger_id: str, reason: str = "scheduled") -> dict:
    t = next((x for x in triggers() if x["id"] == trigger_id), None)
    if not t:
        raise HTTPException(404, f"no trigger {trigger_id}")
    with RUN_LOCKS.setdefault(trigger_id, threading.Lock()):
        started = now(); t0 = time.time()
        RUNNING[trigger_id] = {"started": started, "phase": "starting", "label": "starting", "detail": "", "calls": {}}
        mode = "test" if MODE["test"] else "normal"
        entry = {"ts": started, "trigger": trigger_id, "reason": reason, "mode": mode, "result": "error", "judgment": "",
                 "changes": [], "accounts": None, "audit_id": None, "brief": None, "handoff": None, "duration_s": None,
                 "cost_usd": None, "session_id": None}
        k = killed()
        if k:
            entry.update(result="killed", judgment=f"manual_kill by {k.get('by')} at {k.get('at')}")
        elif not t["_playbook"]:
            entry.update(judgment="no playbook has this trigger.id")
        else:
            cmd = [CLAUDE, "-p", build_prompt(t), "--output-format", "stream-json", "--verbose",
                   "--mcp-config", str(mcp_config_path()),          # reign-tools; account-level connectors (HubSpot) load alongside
                   "--allowedTools", *ALLOWED, "--max-turns", "60"]
            env = {**os.environ, "REIGN_RUNS_DIR": str(P().RUNS)}
            text, returncode, stderr = "", None, ""
            try:
                proc = subprocess.Popen(cmd, cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                deadline = time.time() + 900
                for line in proc.stdout:                          # one JSON event per line; tool calls tell us the phase
                    if time.time() > deadline:
                        proc.kill(); entry["judgment"] = "agent timed out after 900s"; break
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("type") == "assistant":
                        for blk in ev.get("message", {}).get("content", []):
                            if blk.get("type") == "tool_use":
                                _set_phase(trigger_id, blk.get("name", ""), blk.get("input") or {})
                            elif blk.get("type") == "text" and RUNNING.get(trigger_id, {}).get("phase") == "checking":
                                RUNNING[trigger_id].update(phase="judging", label="judging", detail="")
                    elif ev.get("type") == "result":
                        text = ev.get("result", "") or ""
                        entry["cost_usd"] = ev.get("total_cost_usd"); entry["session_id"] = ev.get("session_id")
                proc.wait(timeout=30); returncode = proc.returncode; stderr = proc.stderr.read() if proc.stderr else ""
            except Exception as e:  # noqa: BLE001
                entry["judgment"] = f"runner error: {e}"
            summ = parse_summary(text)
            if summ:
                for key in ("result", "judgment", "changes", "accounts", "audit_id", "brief", "handoff"):
                    if key in summ:
                        entry[key] = summ[key]
            elif not entry["judgment"]:
                entry["judgment"] = f"agent returned no JSON summary (exit {returncode}). tail: {text[-400:]} {stderr[-300:]}"
        entry["duration_s"] = round(time.time() - t0, 1)
        with CFG_LOCK:
            record(entry)
            cfg = load_cfg(); cfg["watches"][trigger_id]["last_run"] = started; save_cfg(cfg)
        RUNNING.pop(trigger_id, None)
        return entry


# ---------------------------------------------------------------- scheduler (normal mode only)
def scheduler():
    while True:
        try:
            if not MODE["test"] and not killed():
                cfg = load_cfg()
                for t in triggers():
                    w = cfg["watches"].get(t["id"], {})
                    if not w.get("enabled") or t["id"] in RUNNING or w.get("last_run") is None:
                        continue                      # never-run watches wait for a manual first check
                    due = (datetime.datetime.fromisoformat(w["last_run"]) + datetime.timedelta(hours=cfg["interval_hours"])
                           <= datetime.datetime.now(datetime.timezone.utc))
                    if due:
                        threading.Thread(target=run_watch, args=(t["id"], "scheduled"), daemon=True).start()
        except Exception as e:  # noqa: BLE001
            print("scheduler:", e, file=sys.stderr)
        time.sleep(30)


# ---------------------------------------------------------------- briefs, results, diffs
def briefs(trigger_id: str | None = None) -> list:
    acts = activity(); out = []
    for d in sorted(P().RUNS.glob("2*"), reverse=True):
        h = d / "handoff.json"
        if not h.exists():
            continue
        ho = json.loads(h.read_text())
        if trigger_id and ho["trigger"] != trigger_id:
            continue
        html = pathlib.Path(ho["brief"])
        m = re.search(r'data-generated-at="([^"]+)"', html.read_text()) if html.exists() else None
        def _has(a):
            ids = a.get("audit_id"); ids = ids if isinstance(ids, list) else [ids]
            return ho["audit_id"] in ids or any(x.get("audit_id") == ho["audit_id"] for x in ((a.get("accounts") or {}).get("affected") or []))
        cycle = next((a for a in acts if _has(a)), None)
        appr = rt.lookup(ho["approval"]["approver"])
        out.append({"run": d.name, "trigger": ho["trigger"], "object": ho["object"], "object_label": ho.get("object_label"),
                    "brief_url": f"/brief/{d.name}/{html.name}",
                    "generated_at": m.group(1) if m else None, "audit_id": ho["audit_id"],
                    "approver": {"id": appr["id"], "name": appr.get("name")}, "approved_at": ho["approval"].get("approved_at"),
                    "approved_by": ho["approval"].get("approved_by"), "origin": "watch cycle" if cycle else "manual run",
                    "changes": (cycle or {}).get("changes", []), "judgment": (cycle or {}).get("judgment")})
    return out


def diffs_for(cycle: dict) -> list:
    f = P().DIFFS
    if not f.exists():
        return []
    t0 = datetime.datetime.fromisoformat(cycle["ts"])
    t1 = t0 + datetime.timedelta(seconds=(cycle.get("duration_s") or 0) + 5)
    return [d for d in (json.loads(l) for l in f.read_text().splitlines() if l.strip())
            if t0 <= datetime.datetime.fromisoformat(d["fetched_at"]) <= t1]


def results(trigger_id: str) -> list:
    rows = [{"kind": "brief", "ts": b["generated_at"], **b} for b in briefs(trigger_id)]
    for c in activity(trigger_id):
        if c.get("accounts"):
            rows.append({"kind": "screen", "ts": c["ts"], "trigger": c["trigger"], "result": c["result"], "judgment": c["judgment"],
                         "affected": c["accounts"].get("affected", []), "excluded": c["accounts"].get("excluded", [])})
        if c["result"] == "noise":
            rows.append({"kind": "noise", "ts": c["ts"], "trigger": c["trigger"], "judgment": c["judgment"],
                         "changes": c.get("changes", []), "duration_s": c.get("duration_s"), "cost_usd": c.get("cost_usd"),
                         "diffs": len(diffs_for(c))})
    return sorted(rows, key=lambda r: r["ts"] or "", reverse=True)


# ---------------------------------------------------------------- test mode
def enter_test(scenario_id: str):
    sc = SCENARIOS.get(scenario_id)
    if not sc:
        raise HTTPException(404, "unknown scenario")
    if RUNNING:
        raise HTTPException(409, "a check is running; wait for it to finish")
    normal = ROOT / "runs"; test = ROOT / "runs-test"
    if test.exists():
        shutil.rmtree(test)
    (test / "watch").mkdir(parents=True)
    if (normal / "cache").exists():
        shutil.copytree(normal / "cache", test / "cache")             # content diffs need the old text
    state = json.loads((normal / "watch" / "state.json").read_text()) if (normal / "watch" / "state.json").exists() else {}
    seeded = []
    for key in sc.get("drop", []):
        state.pop(key, None)                                            # replay "this document did not exist yet"
    for key, fx_name in sc["seeds"].items():
        fx = json.loads((FIXTURES / f"{fx_name}.json").read_text())
        cap = (fx["capture"] + "000000")[:14]; iso = f"{cap[:4]}-{cap[4:6]}-{cap[6:8]}T{cap[8:10]}:{cap[10:12]}:{cap[12:14]}+00:00"
        state[key] = {"sha256": "wayback:" + cap, "fetched_at": iso, "cache": "", "links": fx["links"], "previous": None,
                      "seeded_from": f"Wayback capture {cap}"}
        seeded.append({"url": key, "capture": iso, "links": fx["n_links"]})
    (test / "watch" / "state.json").write_text(json.dumps(state, indent=2))
    cfg = {"interval_hours": 24, "watches": {t["id"]: {"enabled": True, "last_run": None} for t in triggers()}}
    (test / "watch" / "config.json").write_text(json.dumps(cfg, indent=2))
    MODE["test"] = {**sc, "entered_at": now(), "seeded": seeded, "dropped": sc.get("drop", [])}
    (test / "TEST.json").write_text(json.dumps(MODE["test"], indent=2))
    return MODE["test"]


def exit_test():
    if RUNNING:
        raise HTTPException(409, "a check is running; wait for it to finish")
    MODE["test"] = None
    return {"mode": "normal"}


# ---------------------------------------------------------------- API
app = FastAPI(title="reign-server")


class Toggle(BaseModel):
    enabled: bool


class Interval(BaseModel):
    hours: float


class KillReq(BaseModel):
    by: str


class Approve(BaseModel):
    run: str
    by: str


class Scenario(BaseModel):
    scenario: str


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return (HERE / "dashboard.html").read_text()


@app.get("/api/state")
def state():
    cfg = load_cfg(); acts = activity(); nowdt = datetime.datetime.now(datetime.timezone.utc)
    rows = []
    for t in triggers():
        w = cfg["watches"][t["id"]]
        last = next((a for a in reversed(acts) if a["trigger"] == t["id"]), None)
        nxt = None
        if w["enabled"] and not killed() and not MODE["test"]:
            nxt = (datetime.datetime.fromisoformat(w["last_run"]) + datetime.timedelta(hours=cfg["interval_hours"])).isoformat(timespec="seconds") if w["last_run"] else "after first manual check"
        rows.append({"id": t["id"], "title": t.get("title"), "sources": t.get("sources", []), "watch_index": t.get("watch_index", []),
                     "playbook": t["_playbook"], "enabled": w["enabled"], "last_run": w["last_run"], "next_run": nxt,
                     "running": t["id"] in RUNNING, "phase": RUNNING.get(t["id"]), "last": last, "runs": sum(1 for a in acts if a["trigger"] == t["id"]),
                     "briefs": sum(1 for a in acts if a["trigger"] == t["id"] and a["result"] == "brief_emitted"),
                     "noise": sum(1 for a in acts if a["trigger"] == t["id"] and a["result"] == "noise")})
    return {"now": nowdt.isoformat(timespec="seconds"), "interval_hours": cfg["interval_hours"], "killed": killed(),
            "claude": CLAUDE, "watches": rows, "directory": rt._directory()["humans"], "test": MODE["test"],
            "scenarios": [{k: v for k, v in s.items() if k != "seeds"} for s in SCENARIOS.values()],
            "runs_dir": str(runs_dir().relative_to(PROJECT))}


@app.post("/api/interval")
def set_interval(b: Interval):
    cfg = load_cfg(); cfg["interval_hours"] = max(0.05, b.hours); save_cfg(cfg); return {"interval_hours": cfg["interval_hours"]}


@app.post("/api/watch/{trigger_id}")
def set_watch(trigger_id: str, b: Toggle):
    cfg = load_cfg()
    if trigger_id not in cfg["watches"]:
        raise HTTPException(404)
    cfg["watches"][trigger_id]["enabled"] = b.enabled; save_cfg(cfg); return cfg["watches"][trigger_id]


@app.post("/api/run-all")
def run_all():
    cfg = load_cfg()
    started = [t["id"] for t in triggers() if t["id"] not in RUNNING and cfg["watches"][t["id"]]["enabled"]]
    for tid in started:
        threading.Thread(target=run_watch, args=(tid, "manual"), daemon=True).start()
    return {"started": started}


@app.post("/api/run/{trigger_id}")
def run_now(trigger_id: str):
    if trigger_id in RUNNING:
        return {"started": False, "reason": "already running"}
    threading.Thread(target=run_watch, args=(trigger_id, "manual"), daemon=True).start()
    return {"started": True}


@app.post("/api/kill")
def kill(b: KillReq):
    h = rt.lookup(b.by)
    if h.get("kind") != "humans" or not h.get("can_kill"):
        raise HTTPException(403, f"{b.by} is not on the kill list (CEO / CRO only)")
    p = P(); p.RUNS.mkdir(parents=True, exist_ok=True)
    p.KILL.write_text(json.dumps({"by": b.by, "name": h["name"], "at": now()}, indent=2))
    return killed()


@app.post("/api/unkill")
def unkill(b: KillReq):
    h = rt.lookup(b.by)
    if h.get("kind") != "humans" or not h.get("can_kill"):
        raise HTTPException(403, "CEO / CRO only")
    if P().KILL.exists():
        P().KILL.unlink()
    return {"killed": None, "by": b.by}


@app.get("/api/activity/{trigger_id}")
def act(trigger_id: str):
    return list(reversed(activity(trigger_id)))


@app.get("/api/audit")
def audit():
    return audit_rows()


@app.get("/api/audit/{audit_id}")
def audit_one(audit_id: str):
    rec = next((r for r in audit_rows() if r["audit_id"] == audit_id), None)
    if not rec:
        raise HTTPException(404)
    ho = next((json.loads((P().RUNS / b["run"] / "handoff.json").read_text()) for b in briefs() if b["audit_id"] == audit_id), None)
    return {"audit_record": rec, "handoff": ho}


@app.get("/api/briefs")
def briefs_all():
    return briefs()


@app.get("/api/briefs/{trigger_id}")
def briefs_for(trigger_id: str):
    return briefs(trigger_id)


@app.get("/api/results/{trigger_id}")
def results_for(trigger_id: str):
    return results(trigger_id)


@app.get("/api/cycle/{ts}")
def cycle(ts: str):
    c = next((a for a in activity() if a["ts"] == ts), None)
    if not c:
        raise HTTPException(404)
    return {"cycle": c, "diffs": diffs_for(c)}


@app.get("/api/check/{trigger_id}/{ts}")
def check(trigger_id: str, ts: str):
    """Level 3: one check record with the diffs the agent saw, the screened companies, and the briefs it produced.
    Keyed by trigger + ts: 'Check all' starts every watch in the same second, so ts alone is ambiguous."""
    c = next((a for a in activity(trigger_id) if a["ts"] == ts), None)
    if not c:
        raise HTTPException(404)
    ids = c.get("audit_id"); ids = set(ids if isinstance(ids, list) else ([ids] if ids else []))
    acc = c.get("accounts") or {}
    ids |= {a.get("audit_id") for a in acc.get("affected", []) if a.get("audit_id")}
    return {"cycle": c, "diffs": diffs_for(c), "accounts": acc,
            "briefs": [b for b in briefs(c["trigger"]) if b["audit_id"] in ids]}


@app.post("/api/approve")
def approve(b: Approve):
    """The named-human gate before Campaign Manager may send. Sends nothing; the R-17 'message' record is written at send time."""
    h = P().RUNS / b.run / "handoff.json"
    if not h.exists():
        raise HTTPException(404, "no such brief")
    ho = json.loads(h.read_text())
    if rt.lookup(b.by).get("kind") != "humans":
        raise HTTPException(403, f"{b.by} is not a named human")
    if b.by != ho["approval"]["approver"]:
        raise HTTPException(403, f"only {rt.lookup(ho['approval']['approver']).get('name')} ({ho['approval']['approver']}) may approve this brief")
    if not ho["approval"].get("approved_at"):
        ho["approval"].update(approved_at=now(), approved_by=b.by)
        h.write_text(json.dumps(ho, indent=2))
    return ho["approval"]


@app.post("/api/test/enter")
def test_enter(b: Scenario):
    return enter_test(b.scenario)


@app.post("/api/test/exit")
def test_exit():
    return exit_test()


@app.get("/brief/{run}/{name}")
def brief(run: str, name: str):
    p = (P().RUNS / run / name).resolve()
    if not str(p).startswith(str(P().RUNS.resolve())) or not p.exists():
        raise HTTPException(404)
    if p.suffix != ".html":
        return FileResponse(p, media_type="application/json")
    html = p.read_text()
    h = P().RUNS / run / "handoff.json"
    if h.exists():
        ap = json.loads(h.read_text())["approval"]
        if ap.get("approved_at"):
            who = rt.lookup(ap["approved_by"]).get("name", ap["approved_by"])
            html = html.replace("Draft · not yet approved", f"Approved by {who} · {ap['approved_at']}").replace("approved_at null", f"approved_at {ap['approved_at']}")
    return HTMLResponse(html)


if __name__ == "__main__":
    import uvicorn
    threading.Thread(target=scheduler, daemon=True).start()
    print(f"reign-server → http://localhost:8787   claude: {CLAUDE}")
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="warning")
