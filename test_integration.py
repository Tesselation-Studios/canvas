#!/usr/bin/env python3
"""Canvas integration test runner."""
import json, os, sys, time, urllib.request, urllib.error

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
for line in open(env_path):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)

BASE = os.environ.get("CANVAS_URL", "http://localhost:5001").rstrip("/")
# Use localhost for faster tests (avoids TLS overhead through Traefik)
BASE = "http://localhost:5001"
ADMIN = os.environ.get("CANVAS_TOKEN", "")
CASPER = os.environ.get("CASPER_TOKEN", "")


def req(method, path, data=None, token=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return None, str(e)


def json_body(raw):
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


P, F = 0, 0
FAILURES = []


def ok(label):
    global P
    P += 1
    print(f"  [PASS] {label}")


def ko(label, msg=""):
    global F
    F += 1
    FAILURES.append((label, msg))
    print(f"  [FAIL] {label}" + (f"  {msg}" if msg else ""))


TEST_BOARD = f"test-{int(time.time())}"
print(f"\nCanvas Integration Tests\nBoard: {TEST_BOARD}\n")

tests_run = 0

# ── 1. Health & Auth ──
print("── Health & Auth ──")
s, raw = req("GET", "/health")
b = json_body(raw)
ok("GET /health") if s == 200 and b and "database" in b else ko("GET /health", f"{s} {raw[:80]}")
s, raw = req("POST", "/push", {"type": "markdown", "content": "# x"})
ok("No token → 401") if s == 401 else ko("No token → 401", f"{s}")
s, raw = req("POST", "/push", {"type": "markdown", "content": "# x"}, "bad")
ok("Bad token → 401") if s == 401 else ko("Bad token → 401", f"{s}")

# ── 2. Content Types ──
print("\n── Content Types ──")
for ct, d in [
    ("markdown", "# H"),
    ("code", "p"),
    ("mermaid", "graph TD A"),
    ("html", "<b>"),
    ("draw", {"shapes": [{"type": "rect", "x": 0, "y": 0, "w": 100, "h": 50}]}),
    ("app", "<button>C</button>"),
    ("image", "https://x.com/x.png"),
    ("video", "https://youtu.be/dQw4w9WgXcQ"),
]:
    s, raw = req("POST", "/push", {"type": ct, "content": d, "board": TEST_BOARD}, CASPER)
    ok(f"Push {ct}") if s == 200 else ko(f"Push {ct}", f"{s}")

# ── 3. Card Editing ──
print("\n── Card Editing ──")
s, raw = req("POST", "/push", {"type": "markdown", "content": "# Orig", "board": TEST_BOARD, "card_id": "edit-test"}, CASPER)
b = json_body(raw)
ok("Create via card_id") if s == 200 and b and b.get("id") == "edit-test" else ko("Create", f"{s}")

s, raw = req("POST", "/push", {"type": "markdown", "content": "# Updated", "board": TEST_BOARD, "card_id": "edit-test"}, CASPER)
b = json_body(raw)
ok("Update via card_id") if s == 200 and b and b.get("action") == "update" else ko("Update", f"{s}")

time.sleep(0.3)
s, raw = req("GET", f"/history/{TEST_BOARD}")
b = json_body(raw)
found = [c for c in (b.get("cards", []) if b else []) if c.get("id") == "edit-test"]
ok("Verify in history") if len(found) == 1 and "Updated" in found[0]["content"] else ko("Verify", f"{len(found)} found")

s, raw = req("DELETE", "/card/edit-test", token=CASPER)
b = json_body(raw)
ok("Delete card") if s == 200 and b and b.get("action") == "deleted" else ko("Delete", f"{s}")

time.sleep(0.3)
s, raw = req("GET", f"/history/{TEST_BOARD}")
b = json_body(raw)
found = [c for c in (b.get("cards", []) if b else []) if c.get("id") == "edit-test"]
ok("Verify gone") if len(found) == 0 else ko("Verify gone", f"{len(found)} found")

# PUT
s, raw = req("POST", "/push", {"type": "markdown", "content": "# PUT", "board": TEST_BOARD}, CASPER)
b = json_body(raw)
cid = b["id"] if b else ""
s, raw = req("PUT", f"/card/{cid}", {"type": "code", "content": "print(1)", "title": "PUT"}, CASPER)
ok("PUT /card") if s == 200 else ko("PUT", f"{s}")
time.sleep(0.3)
s, raw = req("GET", f"/history/{TEST_BOARD}")
b = json_body(raw)
found = [c for c in (b.get("cards", []) if b else []) if c.get("id") == cid]
ok("PUT verify type changed") if len(found) == 1 and found[0].get("type") == "code" else ko("PUT verify", "")

# PATCH
s, raw = req("POST", "/push", {"type": "markdown", "content": "# PATCH", "title": "Old", "board": TEST_BOARD}, CASPER)
b = json_body(raw)
cid = b["id"] if b else ""
s, raw = req("PATCH", f"/card/{cid}", {"title": "New"}, CASPER)
ok("PATCH /card") if s == 200 else ko("PATCH", f"{s}")
time.sleep(0.3)
s, raw = req("GET", f"/history/{TEST_BOARD}")
b = json_body(raw)
found = [c for c in (b.get("cards", []) if b else []) if c.get("id") == cid]
ok("PATCH verify partial") if len(found) == 1 and found[0].get("title") == "New" and found[0].get("content") == "# PATCH" else ko("PATCH verify", "")

# ── 4. Identity Override ──
print("\n── Identity Override ──")
s, raw = req("POST", "/push", {"type": "markdown", "content": "# ID", "board": TEST_BOARD, "agent": "evil", "agent_emoji": "💀"}, CASPER)
b = json_body(raw)
cid = b["id"] if b else ""
time.sleep(0.3)
s, raw = req("GET", f"/history/{TEST_BOARD}")
b = json_body(raw)
found = [c for c in (b.get("cards", []) if b else []) if c.get("id") == cid]
ok("Auth overrides agent/emoji") if found and found[0]["agent"] == "casper" and found[0]["agent_emoji"] == "👻" else ko("Identity", f"{found}")

# ── 5. Expiry ──
print("\n── Expiry ──")
s, raw = req("POST", "/push", {"type": "markdown", "content": "# F", "board": TEST_BOARD, "expires_at": "2099-12-31T23:59:59"}, CASPER)
b = json_body(raw)
fid = b["id"] if b else ""
s, raw = req("POST", "/push", {"type": "markdown", "content": "# P", "board": TEST_BOARD, "expires_at": "2020-01-01T00:00:00"}, CASPER)
b = json_body(raw)
pid = b["id"] if b else ""
s, raw = req("POST", "/push", {"type": "markdown", "content": "# D", "board": TEST_BOARD}, CASPER)
b = json_body(raw)
did = b["id"] if b else ""
time.sleep(0.5)
s, raw = req("GET", f"/history/{TEST_BOARD}")
b = json_body(raw)
cards = b.get("cards", []) if b else []
ok("Future visible") if len([x for x in cards if x.get("id") == fid]) == 1 else ko("Future", "")
ok("Past hidden") if len([x for x in cards if x.get("id") == pid]) == 0 else ko("Past", "")
ok("Default visible") if len([x for x in cards if x.get("id") == did]) == 1 else ko("Default", "")

# ── 6. Board Isolation ──
print("\n── Board Isolation ──")
req("POST", "/push", {"type": "markdown", "content": "# A", "board": "iso-ta"}, CASPER)
req("POST", "/push", {"type": "markdown", "content": "# B", "board": "iso-tb"}, CASPER)
time.sleep(0.3)
s_a, raw_a = req("GET", "/history/iso-ta")
s_b, raw_b = req("GET", "/history/iso-tb")
b_a = json_body(raw_a)
b_b = json_body(raw_b)
ok("Boards isolated") if b_a and b_b and len(b_a.get("cards", [])) > 0 and len(b_b.get("cards", [])) > 0 else ko("Isolation", "")

# ── 7. Token Management ──
print("\n── Token Management ──")
s, raw = req("POST", "/token", {"agent": "bot-tt", "agent_emoji": "🤖"}, ADMIN)
b = json_body(raw)
bt = b.get("token", "") if b else ""
ok("POST /token") if s == 200 and bt else ko("POST /token", f"{s}")
s, raw = req("POST", "/push", {"type": "markdown", "content": "# Bot", "board": TEST_BOARD}, bt)
ok("Push with new token") if s == 200 else ko("Push w/new token", f"{s}")
s, raw = req("DELETE", "/token", {"agent": "bot-tt"}, ADMIN)
ok("DELETE /token") if s == 200 else ko("DELETE /token", f"{s}")
time.sleep(0.3)
s, raw = req("POST", "/push", {"type": "markdown", "content": "# Fail", "board": TEST_BOARD}, bt)
ok("Revoked token → 401") if s == 401 else ko("Revoked token", f"{s}")

# ── 8. Clear Board ──
print("\n── Clear Board ──")
for i in range(3):
    req("POST", "/push", {"type": "markdown", "content": f"#{i}", "board": "clr-tt"}, CASPER)
time.sleep(0.3)
s, raw = req("GET", "/history/clr-tt")
b = json_body(raw)
bc = len(b.get("cards", [])) if b else 0
req("POST", "/push", {"type": "clear", "board": "clr-tt"}, CASPER)
time.sleep(0.3)
s, raw = req("GET", "/history/clr-tt")
b = json_body(raw)
ac = len(b.get("cards", [])) if b else 0
ok("Push → clear → empty") if bc > 0 and ac == 0 else ko("Clear", f"before={bc} after={ac}")

# ── 9. Pagination ──
print("\n── Pagination ──")
for i in range(25):
    req("POST", "/push", {"type": "markdown", "content": f"# Card {i}", "board": "pag-tt"}, CASPER)
time.sleep(1.0)
s, raw = req("GET", "/history/pag-tt")
b = json_body(raw)
cards = b.get("cards", []) if b else []
total = b.get("total", 0) if b else 0
ok("Page size 20") if len(cards) == 20 else ko("Page size", f"got {len(cards)}")
ok(f"Total >= 25") if total >= 25 else ko("Total", f"total={total}")

# ── 10. Boards & Reload ──
print("\n── Boards & Reload ──")
s, raw = req("GET", "/boards")
b = json_body(raw)
ok("GET /boards") if s == 200 and isinstance(b, list) else ko("Boards", "")
s, raw = req("POST", "/reload", token=ADMIN)
b = json_body(raw)
ok("POST /reload") if s == 200 and b and b.get("status") == "ok" else ko("Reload", "")
s, raw = req("POST", "/reload")
ok("POST /reload (no auth) → 401") if s == 401 else ko("Reload 401", f"{s}")

# ── 11. Card Page ──
print("\n── Card Page ──")
# Create a card specifically for the card page test
s, raw = req("POST", "/push", {"type": "markdown", "content": "# Card Page Test", "board": TEST_BOARD}, CASPER)
b = json_body(raw)
card_page_id = b.get("id", "") if b else ""
s, raw = req("GET", f"/card/{card_page_id}")
ok("GET /card/<id>") if s == 200 else ko("Card page", f"{s} for {card_page_id}")
s, raw = req("GET", "/card/nonexistent-id")
ok("GET /card/<bad> handled") if s in (200, 404) else ko("Card bad", f"{s}")

# ── 12. Content Validation ──
print("\n── Content Validation ──")
s, raw = req("POST", "/push", {"type": "latex", "content": "x", "board": TEST_BOARD}, CASPER)
b = json_body(raw)
ok("Invalid type → 400") if s == 400 else ko("Invalid type", f"{s}")
s, raw = req("POST", "/push", {"type": "markdown", "content": "", "board": TEST_BOARD}, CASPER)
b = json_body(raw)
ok("Missing content → 400") if s == 400 else ko("Missing content", f"{s}")

# ── Summary ──
print(f"\n{'=' * 50}")
print(f"Results: {P} PASS  {F} FAIL")
print(f"{'=' * 50}")
if FAILURES:
    print("\nFailed:")
    for label, msg in FAILURES:
        print(f"  ✗ {label}: {msg}")

with open(os.path.join(os.path.dirname(__file__), "test_results.log"), "w") as f:
    f.write(f"Canvas Integration Tests\nResults: {P} PASS, {F} FAIL\n")
    if FAILURES:
        f.write("Failed:\n")
        for l, m in FAILURES:
            f.write(f"  ✗ {l}: {m}\n")

sys.exit(0 if F == 0 else 1)