#!/usr/bin/env python3
"""
brief_eval.py — hard checks on a generated brief (HTML). Exit 0 = PASS, 1 = FAIL.

  python brief_eval.py runs/<ts>/brief-sr-26-2.html [--refetch]

Checks
  1. cited      every <p> in sections 1–2 carries at least one <a class="cite" href="#src-n">, and every n resolves to <li id="src-n">
  2. length     word count of sections 1–3 ≤ 250
  3. banned     no phrase from banned_phrases.txt appears
  4. sources    each <li id="src-n"> has href, data-fetched-at, data-sha256; cached text re-hashes to data-sha256 (--refetch: re-download and compare)
  5. audit      runs/audit.jsonl has a record with audit_id = article[data-audit-id], object matches, written_at < data-generated-at
  6. send       article[data-send] == "false", or data-approver is a human in the directory
  7. one-ask    section 3 contains exactly one sentence
"""
import argparse, hashlib, json, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "mcp"))
import reign_tools as rt  # noqa: E402


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


def section(html: str, n: int) -> str:
    m = re.search(rf'<section[^>]*data-section="{n}"[^>]*>(.*?)</section>', html, re.S)
    return m.group(1) if m else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("brief")
    ap.add_argument("--refetch", action="store_true")
    a = ap.parse_args()
    html = pathlib.Path(a.brief).read_text()
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))   # coerce: a truthy set here once crashed the summary sum()

    art = re.search(r"<article([^>]*)>", html)
    attrs = dict(re.findall(r'data-([\w-]+)="([^"]*)"', art.group(1))) if art else {}

    # 1. cited
    src_ids = set(re.findall(r'<li[^>]*id="src-(\d+)"', html))
    uncited, dangling = [], []
    for n in (1, 2):
        for p in re.findall(r"<p\b[^>]*>(.*?)</p>", section(html, n), re.S):
            cites = re.findall(r'<a class="cite" href="#src-(\d+)"', p)
            if not cites:
                uncited.append(text_of(p)[:60])
            dangling += [c for c in cites if c not in src_ids]
    check("cited", not uncited and not dangling,
          f"uncited={uncited} dangling={dangling}" if (uncited or dangling) else f"{len(src_ids)} sources")

    # 2. length
    words = sum(len(text_of(section(html, n)).split()) for n in (1, 2, 3))
    check("length", words <= 250, f"{words} words")

    # 3. banned
    body = text_of(section(html, 1) + section(html, 2) + section(html, 3)).lower()
    banned = [l.strip() for l in (HERE / "banned_phrases.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
    hits = [b for b in banned if b.lower() in body]
    check("banned", not hits, f"hits={hits}" if hits else "clean")

    # 4. sources
    bad = []
    for m in re.finditer(r'<li[^>]*id="src-(\d+)"([^>]*)>(.*?)</li>', html, re.S):
        n, li_attrs, inner = m.group(1), m.group(2), m.group(3)
        d = dict(re.findall(r'data-([\w-]+)="([^"]*)"', li_attrs))
        href = re.search(r'href="([^"]+)"', inner)
        if not (href and d.get("fetched-at") and d.get("sha256")):
            bad.append(f"src-{n}: missing href/fetched-at/sha256"); continue
        if a.refetch:
            try:
                got = rt.fetch_source(href.group(1))["sha256"]
            except Exception as e:  # noqa: BLE001
                bad.append(f"src-{n}: refetch failed {e}"); continue
        else:
            cache = rt.CACHE / f"{d['sha256']}.txt"
            if not cache.exists():
                bad.append(f"src-{n}: no cached text for hash"); continue
            got = hashlib.sha256(cache.read_text().encode()).hexdigest()
        if got != d["sha256"]:
            bad.append(f"src-{n}: hash changed")
    check("sources", not bad and src_ids, "; ".join(bad) if bad else ("refetched, all match" if a.refetch else "cache hashes match"))

    # 5. audit
    aid, obj, gen = attrs.get("audit-id"), attrs.get("object"), attrs.get("generated-at")
    rec = None
    if rt.AUDIT_LOG.exists():
        for line in rt.AUDIT_LOG.read_text().splitlines():
            r = json.loads(line)
            if r.get("audit_id") == aid:
                rec = r
    ok = bool(rec) and rec.get("object") == obj and bool(gen) and rec.get("written_at") < gen
    check("audit", ok, f"{aid} written_at={rec.get('written_at') if rec else None} generated_at={gen} object={obj}")

    # 6. send
    approver_ok = rt.lookup(attrs.get("approver", "")).get("kind") == "humans"
    check("send", attrs.get("send") == "false" or approver_ok, f"send={attrs.get('send')} approver={attrs.get('approver')}")

    # 7. one-ask
    ask = text_of(section(html, 3))
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", ask) if s.strip()]
    check("one-ask", len(sentences) == 1, f"{len(sentences)} sentence(s)")

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    passed = all(ok for _, ok, _ in results)
    print(f"\n{'PASS' if passed else 'FAIL'}  {sum(ok for _, ok, _ in results)}/{len(results)}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
