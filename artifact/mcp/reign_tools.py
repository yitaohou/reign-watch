#!/usr/bin/env python3
"""
Reign tools — the four tools the regulatory-brief skill needs.

Runs two ways, same code path:
  MCP server (stdio):   python reign_tools.py serve
  CLI:                  python reign_tools.py fetch <url> | audit <record.json> | lookup <id> | check-kill <playbook.json> <state.json>

Stand-ins, to be swapped on day one:
  write_audit  → HubSpot timeline (system of record per CEO note)
  lookup       → HubSpot contacts / ZoomInfo
Fail-closed by design: write_audit raises on any R-17 gap; a raise means the action must not proceed.
"""
import argparse, datetime, hashlib, html, io, json, os, pathlib, re, sys, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]          # artifact/
DATA = ROOT / "data"
RUNS = pathlib.Path(os.environ.get("REIGN_RUNS_DIR") or ROOT / "runs")   # test mode points this at runs-test/
CACHE, AUDIT_LOG = RUNS / "cache", RUNS / "audit.jsonl"
R17_FIELDS = ["actor", "principal", "action", "object", "purpose", "sources", "send"]
R17_ACTIONS = {"create", "update", "enrich", "score", "message"}
UA = "reign-brief/0.1 (iTmethods; regulatory trigger watcher)"


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- fetch_source
def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|nav|footer|header)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def fetch_source(url: str, max_chars: int = 20000) -> dict:
    """Fetch a URL. Returns text (truncated), fetched_at, and a sha256 of the *extracted text*
    (raw bytes churn on dynamic pages; text is what the brief cites). Full text is cached by hash."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        raw, ctype = r.read(), r.headers.get("Content-Type", "")
    links = []
    if "pdf" in ctype.lower() or url.lower().endswith(".pdf"):
        from pypdf import PdfReader
        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages)
    else:
        from urllib.parse import urljoin
        page = raw.decode("utf-8", "replace")
        links = sorted({urljoin(url, h) for h in re.findall(r'href="([^"#]+)"', page)
                        if not h.startswith(("mailto:", "javascript:", "tel:"))})[:2000]
        text = _html_to_text(page)
    text = text.replace("\r\n", "\n").replace("\r", "\n")   # read_text() would normalise these; hash the normalised form
    sha = hashlib.sha256(text.encode()).hexdigest()
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{sha}.txt").write_text(text)
    return {"url": url, "fetched_at": now(), "sha256": sha, "content_type": ctype,
            "bytes": len(raw), "chars": len(text), "cache": str(CACHE / f"{sha}.txt"),
            "links": links, "text": text[:max_chars]}


# ---------------------------------------------------------------- diff_source (the watcher's memory)
WATCH_STATE = RUNS / "watch" / "state.json"


def _load_state() -> dict:
    return json.loads(WATCH_STATE.read_text()) if WATCH_STATE.exists() else {}


def _save_state(s: dict):
    WATCH_STATE.parent.mkdir(parents=True, exist_ok=True)
    WATCH_STATE.write_text(json.dumps(s, indent=2))


def diff_source(url: str, watch_index: bool = False, max_lines: int = 60) -> dict:
    """Fetch url and compare with the last snapshot, then store the new snapshot.
    Content page (default): changed = sha256 of extracted text differs; returns added/removed lines.
    Index page (watch_index=True): changed = new links appeared; text churn is ignored.
    First call on a URL returns first_seen=True (baseline, not a change). The agent judges materiality; this tool only reports."""
    import difflib, fcntl
    cur = fetch_source(url, max_chars=0)             # network outside the lock
    key = f"{url}#index" if watch_index else url     # a URL watched both as content and as index keeps two snapshots
    WATCH_STATE.parent.mkdir(parents=True, exist_ok=True)
    lock = open(WATCH_STATE.with_suffix(".lock"), "w"); fcntl.flock(lock, fcntl.LOCK_EX)   # parallel cycles share this file
    state = _load_state(); prev = state.get(key)
    out = {"url": url, "fetched_at": cur["fetched_at"], "sha256": cur["sha256"], "cache": cur["cache"],
           "watch_index": watch_index, "first_seen": prev is None, "changed": False,
           "old_sha256": prev["sha256"] if prev else None, "old_fetched_at": prev["fetched_at"] if prev else None,
           "added": [], "removed": [], "new_links": [], "gone_links": []}
    if prev:
        if watch_index:
            old, new = set(prev.get("links", [])), set(cur["links"])
            out["new_links"], out["gone_links"] = sorted(new - old), sorted(old - new)
            out["changed"] = bool(out["new_links"])
        else:
            out["changed"] = prev["sha256"] != cur["sha256"]
            if out["changed"]:
                old_p = pathlib.Path(prev["cache"])
                old_txt = old_p.read_text().splitlines() if old_p.exists() else []
                new_txt = pathlib.Path(cur["cache"]).read_text().splitlines()
                d = list(difflib.unified_diff(old_txt, new_txt, lineterm="", n=0))
                out["added"] = [l[1:] for l in d if l.startswith("+") and not l.startswith("+++")][:max_lines]
                out["removed"] = [l[1:] for l in d if l.startswith("-") and not l.startswith("---")][:max_lines]
    state[key] = {"sha256": cur["sha256"], "fetched_at": cur["fetched_at"], "cache": cur["cache"],
                  "links": cur["links"] if watch_index else [],
                  "previous": {"sha256": prev["sha256"], "fetched_at": prev["fetched_at"]} if prev else None}
    _save_state(state)
    if out["changed"]:                                # keep the evidence: what the agent saw, independent of what it concluded
        full = dict(out); full["added"], full["removed"] = out["added"][:400], out["removed"][:400]
        with (WATCH_STATE.parent / "diffs.jsonl").open("a") as f:
            f.write(json.dumps(full) + "\n")
    fcntl.flock(lock, fcntl.LOCK_UN); lock.close()
    return out


# ---------------------------------------------------------------- lookup
def _directory() -> dict:
    return json.loads((DATA / "directory.json").read_text())


def lookup(id: str) -> dict:
    """Resolve a hum-/agt-/acct-/cont- id from the mock directory. Stand-in for HubSpot / ZoomInfo."""
    d = _directory()
    for kind in ("humans", "agents", "prospects"):
        if id in d[kind]:
            return {"id": id, "kind": kind, **d[kind][id]}
    return {"id": id, "kind": None, "error": "not found"}


# ---------------------------------------------------------------- write_audit
def write_audit(record: dict) -> dict:
    """Write an R-17 record. Raises (= action must not happen) on any gap:
    missing field, unknown action, send without approver, vague purpose, unresolvable principal/approver."""
    missing = [f for f in R17_FIELDS if f not in record or record[f] in (None, "", [])]
    if missing:
        raise ValueError(f"R-17: missing {missing} — record not written, action must not proceed")
    if record["action"] not in R17_ACTIONS:
        raise ValueError(f"R-17: action must be one of {sorted(R17_ACTIONS)}")
    if record["send"] is True and not record.get("approver"):
        raise ValueError("R-17: send=true requires a named approver")
    purpose = record["purpose"].strip()
    if len(purpose.split()) < 6 or purpose.lower().rstrip(".") in {"engagement", "outreach", "awareness"}:
        raise ValueError("R-17: purpose must be one specific sentence, not 'engagement'")
    for role in ("principal",) + (("approver",) if record.get("approver") else ()):
        if lookup(record[role]).get("kind") != "humans":
            raise ValueError(f"R-17: {role} '{record[role]}' is not a named human in the directory")
    ref = record.get("object_ref") or {}
    if lookup(record["object"]).get("kind") != "prospects" and not (ref.get("system") == "hubspot" and ref.get("id")):
        raise ValueError(f"R-17: object '{record['object']}' is not a known account or contact (no directory entry, no HubSpot id)")
    for s in record["sources"]:
        if not (isinstance(s, dict) and s.get("url") and s.get("fetched_at") and s.get("sha256")):
            raise ValueError("R-17: each source needs url, fetched_at, sha256")
    RUNS.mkdir(parents=True, exist_ok=True)
    written_at = now()
    audit_id = "aud-" + hashlib.sha256(f"{written_at}{record['object']}{record['action']}".encode()).hexdigest()[:10]
    rec = {"audit_id": audit_id, "written_at": written_at, **record}
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return {"ok": True, "audit_id": audit_id, "written_at": written_at,
            "sink": str(AUDIT_LOG), "sink_note": "stand-in for HubSpot timeline"}


# ---------------------------------------------------------------- check_kill
def check_kill(playbook: dict, state: dict) -> dict:
    """Evaluate the playbook's kill_criteria against run state.
    state: {audit_ok, send, briefing_booked, sources:[{url, ok, hash_match}], manual_kill_by}"""
    seg = playbook["audience"]["segment"]
    fs = seg.startswith("D-SIB")
    ch, appr = playbook["channel"], playbook["approval"].get("approver")
    ttype = playbook["trigger"]["type"]
    ids = {k["id"]: k for k in playbook["kill_criteria"]}
    tripped = []
    if "audit_write_failed" in ids and fs and not state.get("audit_ok"):
        tripped.append({"id": "audit_write_failed", "action": "abort"})
    if "channel_unknown" in ids and ch == "unknown":
        tripped.append({"id": "channel_unknown", "action": "block_send"})
    if "approver_missing" in ids and state.get("send") and not appr:
        tripped.append({"id": "approver_missing", "action": "block_send"})
    if "source_stale" in ids:
        bad = [s["url"] for s in state.get("sources", []) if not s.get("ok") or s.get("hash_match") is False]
        if bad:
            tripped.append({"id": "source_stale", "action": "block_send", "sources": bad})
    if "briefing_not_booked" in ids and fs and ch != "briefing" and not state.get("briefing_booked") and ttype != "regulatory":
        tripped.append({"id": "briefing_not_booked", "action": "block_send"})
    mk = state.get("manual_kill_by")
    if "manual_kill" in ids and mk:
        if mk in ids["manual_kill"]["by"]:
            tripped.append({"id": "manual_kill", "action": "abort", "by": mk})
        else:
            tripped.append({"id": "manual_kill", "action": "ignored", "note": f"{mk} is not on the kill list"})
    live = [t for t in tripped if t["action"] in ("abort", "block_send")]
    return {"blocked": bool(live), "abort": any(t["action"] == "abort" for t in live), "tripped": tripped}


# ---------------------------------------------------------------- audited (structural enforcement)
def audited(fn):
    """Decorator: the wrapped action cannot run unless its R-17 record has been written.
    Usage: fn(record, *args) → writes record, then calls fn(audit_result, *args).
    If write_audit raises, fn never executes. This is the code-level form of
    'if the record cannot be written, the action does not happen'."""
    def wrapper(record: dict, *args, **kw):
        audit = write_audit(record)          # raises → action never happens
        return fn(audit, *args, **kw)
    wrapper.__name__, wrapper.__doc__ = fn.__name__, fn.__doc__
    return wrapper


# ---------------------------------------------------------------- emit_brief (the only way a brief becomes a file)
BRIEF_CSS = """
:root{--bg:#F4F6F8;--surface:#fff;--ink:#171B22;--muted:#5B6470;--rule:#D8DDE4;--accent:#1F5F7A;--warn:#B3721B;--mono:#EEF1F4}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#12161B;--surface:#1A1F26;--ink:#E6EAEE;--muted:#9AA4B0;--rule:#2C333C;--accent:#6FB3CF;--warn:#E0A756;--mono:#222830}}
:root[data-theme=dark]{--bg:#12161B;--surface:#1A1F26;--ink:#E6EAEE;--muted:#9AA4B0;--rule:#2C333C;--accent:#6FB3CF;--warn:#E0A756;--mono:#222830}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 "IBM Plex Sans","Helvetica Neue",Arial,sans-serif;padding:40px 20px 64px}
article{max-width:680px;margin:0 auto;background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:32px 36px}
header{display:grid;gap:6px;padding-bottom:18px;border-bottom:1px solid var(--rule);margin-bottom:8px}
.eyebrow{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:500}
h1{font:600 24px/1.2 "Source Serif 4",Georgia,serif;margin:0;text-wrap:balance}
.status{display:inline-block;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--warn);border:1px solid var(--warn);border-radius:999px;padding:2px 9px;width:max-content}
h2{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:500;margin:22px 0 6px}
p{margin:0 0 10px;max-width:62ch}
a.cite{color:var(--accent);text-decoration:none;font-size:12px;vertical-align:super;margin-left:1px}
a.cite:hover{text-decoration:underline}
ol{margin:0;padding-left:20px;display:grid;gap:8px}
li a{color:var(--accent);word-break:break-all}
li small{display:block;color:var(--muted);font:12px/1.4 "IBM Plex Mono",ui-monospace,Menlo,monospace}
footer{margin-top:24px;padding-top:14px;border-top:1px solid var(--rule);color:var(--muted);font:12px/1.5 "IBM Plex Mono",ui-monospace,Menlo,monospace}
code{font:12.5px/1 "IBM Plex Mono",ui-monospace,Menlo,monospace;background:var(--mono);padding:2px 5px;border-radius:3px}
"""


def _render_brief(playbook, trigger, sources, body_html, contact, audit, generated_at, object_label=None) -> str:
    acct = lookup(playbook["audit"]["object"])
    if object_label:
        acct = {**acct, "label": object_label}
    approver, principal = lookup(playbook["approval"]["approver"]), lookup(playbook["audit"]["principal"])
    items = []
    for i, s in enumerate(sources, 1):
        title = html.escape(s.get("title") or s["url"])
        items.append(f'<li id="src-{i}" data-fetched-at="{s["fetched_at"]}" data-sha256="{s["sha256"]}">'
                     f'<a href="{html.escape(s["url"])}" target="_blank" rel="noopener">{title}</a>'
                     f'<small>fetched {s["fetched_at"]} · sha256 {s["sha256"][:12]}…</small></li>')
    date = generated_at[:10]
    return f"""<title>Brief · {html.escape(trigger["id"])} · {html.escape(acct.get("label", acct["id"]))}</title>
<style>{BRIEF_CSS}</style>
<article data-playbook="{playbook["playbook_id"]}@{playbook["version"]}" data-trigger="{trigger["id"]}"
         data-object="{playbook["audit"]["object"]}" data-audit-id="{audit["audit_id"]}"
         data-generated-at="{generated_at}" data-send="false" data-approver="{playbook["approval"]["approver"]}">
  <header>
    <div class="eyebrow">Reign · Regulatory brief · {html.escape(trigger["id"])} · prepared {date} · for the {html.escape(contact)}</div>
    <h1>{html.escape(trigger.get("title", trigger["id"]))}</h1>
    <span class="status">Draft · not yet approved</span>
  </header>
{body_html}
  <section data-section="4">
    <h2>Sources</h2>
    <ol>
      {"".join(items)}
    </ol>
  </section>
  <footer>audit {audit["audit_id"]} · actor {playbook["audit"]["actor"]} · principal {html.escape(principal.get("name","?"))} ({playbook["audit"]["principal"]}) · approver {html.escape(approver.get("name","?"))} ({playbook["approval"]["approver"]}) · approved_at null · send false · Reign R-17</footer>
</article>
"""


@audited
def _persist_brief(audit, playbook, trigger, sources, body_html, contact, run_dir, object_label=None, object_ref=None):
    """Runs only after the audit record is written. Renders, writes, evals, hands off."""
    import subprocess
    generated_at = now()
    if generated_at <= audit["written_at"]:            # same-second guard: brief must post-date the record
        import time; time.sleep(1); generated_at = now()
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"brief-{trigger['id'].lower()}.html"
    out.write_text(_render_brief(playbook, trigger, sources, body_html, contact, audit, generated_at, object_label))
    ev = subprocess.run([sys.executable, str(ROOT / "eval" / "brief_eval.py"), str(out)], capture_output=True, text=True)
    passed = ev.returncode == 0
    result = {"audit_id": audit["audit_id"], "written_at": audit["written_at"], "generated_at": generated_at,
              "brief": str(out), "eval": "PASS" if passed else "FAIL", "eval_output": ev.stdout.strip()}
    if passed:
        handoff = {"for": "Campaign Manager", "playbook_id": playbook["playbook_id"], "version": playbook["version"],
                   "trigger": trigger["id"], "object": playbook["audit"]["object"], "object_label": object_label,
                   "object_ref": object_ref, "channel": playbook["channel"],
                   "brief": str(out), "audit_id": audit["audit_id"],
                   "approval": {"approver": playbook["approval"]["approver"], "approved_at": None},
                   "send": False, "note": "Nothing has been sent. CM enforces approval and kill_criteria; check_kill here was pre-flight only.",
                   "send_requires": {   # R-17: sending is a second action ('message') and needs its own record
                       "action": "message", "send": True, "approver": playbook["approval"]["approver"],
                       "approved_at": "non-null, set by the approver", "object": "the contact id (cont-…), not the account",
                       "actor": "whatever sends — CM or a human", "principal": playbook["audit"]["principal"],
                       "sources": "same list as the create record", "purpose": "one specific sentence"}}
        (run_dir / "handoff.json").write_text(json.dumps(handoff, indent=2))
        result["handoff"] = str(run_dir / "handoff.json")
    else:
        failed = out.with_suffix(".FAILED.html"); out.rename(failed); result["brief"] = str(failed)
    return result


def emit_brief(playbook_path: str, trigger_path: str, sources: list, body_html: str, contact: str = "Chief Audit Executive",
               object: str | None = None, object_label: str | None = None, hubspot_id: str | None = None,
               purpose: str | None = None) -> dict:
    """The ONLY way a brief becomes a file. Writes the R-17 record first (fail-closed), then renders
    sections 1–3 (body_html) into the template with clickable sources, runs the eval, and writes handoff.json
    for Campaign Manager if it passes. sources = the dicts returned by fetch_source (+ optional 'title').
    Per-account fan-out: pass object (reign account id), object_label (company name) and hubspot_id to
    instantiate the playbook template for that account; the R-17 record carries object_ref {system: hubspot, id}."""
    playbook = json.loads(pathlib.Path(playbook_path).read_text())
    trigger = json.loads(pathlib.Path(trigger_path).read_text())
    object_ref = {"system": "hubspot", "id": str(hubspot_id)} if hubspot_id else None
    if object:
        playbook = {**playbook, "audit": {**playbook["audit"], "object": object}}
    if purpose:
        playbook = {**playbook, "audit": {**playbook["audit"], "purpose": purpose}}
    record = {**playbook["audit"],
              "sources": [{"url": s["url"], "fetched_at": s["fetched_at"], "sha256": s["sha256"]} for s in sources]}
    if object_ref:
        record["object_ref"] = object_ref
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / (f"{stamp}-{object}" if object else stamp)
    return _persist_brief(record, playbook, trigger, sources, body_html, contact, run_dir, object_label, object_ref)


# ---------------------------------------------------------------- MCP + CLI
def serve():
    try:                                   # mcp 2.x renamed FastMCP → MCPServer
        from mcp.server.mcpserver import MCPServer as _Server
    except ModuleNotFoundError:            # mcp 1.x
        from mcp.server.fastmcp import FastMCP as _Server
    mcp = _Server("reign-tools")
    for t in (fetch_source, diff_source, lookup, write_audit, check_kill, emit_brief):
        mcp.tool()(t)
    mcp.run()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    f = sub.add_parser("fetch"); f.add_argument("url"); f.add_argument("--max-chars", type=int, default=2000)
    d = sub.add_parser("diff"); d.add_argument("url"); d.add_argument("--index", action="store_true")
    sub.add_parser("lookup").add_argument("id")
    sub.add_parser("audit").add_argument("record_json")
    k = sub.add_parser("check-kill"); k.add_argument("playbook_json"); k.add_argument("state_json")
    e = sub.add_parser("emit", help="emit a brief: playbook, trigger, sources.json (list from fetch), body.html, --contact")
    e.add_argument("playbook_json"); e.add_argument("trigger_json"); e.add_argument("sources_json"); e.add_argument("body_html")
    e.add_argument("--contact", default="Chief Audit Executive")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        return serve()
    if a.cmd == "fetch":
        out = fetch_source(a.url, a.max_chars)
    elif a.cmd == "diff":
        out = diff_source(a.url, a.index)
    elif a.cmd == "lookup":
        out = lookup(a.id)
    elif a.cmd == "audit":
        try:
            out = write_audit(json.loads(pathlib.Path(a.record_json).read_text()))
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}, indent=2)); sys.exit(2)
    elif a.cmd == "check-kill":
        out = check_kill(json.loads(pathlib.Path(a.playbook_json).read_text()),
                         json.loads(pathlib.Path(a.state_json).read_text()))
    else:
        try:
            out = emit_brief(a.playbook_json, a.trigger_json, json.loads(pathlib.Path(a.sources_json).read_text()),
                             pathlib.Path(a.body_html).read_text(), a.contact)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e), "note": "audit refused → brief not written"}, indent=2)); sys.exit(2)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
