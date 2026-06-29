# Canvas — Real-time Agent Display Board Specification

> **Status:** Revision 3 — Deployed state
> **Author:** Orchestrator (subagent) / Coder (subagent)
> **Date:** 2026-06-29
> **Iteration:** 3
> **Spec driven from:** What's actually running on OpenClaw VM (192.168.1.73)

### Revision History

| Iteration | Date | Changes |
|---|---|---|
| 1 | 2026-06-27 | Initial draft for Raf review |
| 2 | 2026-06-27 | Remove all trading references; genericize board examples |
| 3 | 2026-06-29 | Update to reflect deployed reality: no Docker, SQLite persistence, card permalinks, card editing, full CDN template, draw/app content types, newest-first scrolling, nohup runtime, known limitations |
| 4 | 2026-06-29 | Lazy loading (infinite scroll via paginated history), card expiry (`expires_at` column), GitHub repo, issue tracker, updated known issues |

---

## 1. Purpose

Canvas is a **real-time visual display surface** where AI agents push content and Raf watches it render live in a browser. Think: a shared dashboard / live-updating whiteboard for an AI+human team.

### What problem does it solve?

- Raf runs multiple AI agents (Casper, Gonzo, Researcher, etc.) that produce text, code, diagrams, images, videos, and interactive HTML
- Before Canvas, results lived in logs or Telegram threads — ephemeral, hard to glance at, no visual hierarchy
- Canvas gives Raf a **persistent, multi-board, real-time window** into what agents are producing
- Agents push via `POST /push`; SSE streams updates to the browser instantly — no polling, no refresh

### What it is NOT

- NOT a document editor (you can't type into it)
- Board history is persisted in SQLite (`data/canvas.db`) — in-memory `BOARDS` dict is a cache loaded from the database on startup

---

## 2. User Stories

### As Raf (Viewer)

| # | Story |
|---|---|
| U1 | Open `canvas.wodinga.studio` and see a live stream of agent pushes on the "main" board |
| U2 | Open `canvas.wodinga.studio/?board=dashboards` and see only dashboard-related pushes |
| U3 | Watch new content appear **instantly** without refreshing the page |
| U4 | See agent identity (name + emoji) on each card |
| U5 | Scroll back through all history — no arbitrary cap; SQLite persists everything |
| U6 | Clear a board when it gets cluttered |
| U7 | See markdown rendered, code highlighted, Mermaid diagrams drawn, SVG shapes, HTML sandboxes, images, and videos |
| U8 | Click 🔗 on any card to copy a permalink — share links to specific cards via `canvas.wodinga.studio/#card-<uuid>` |
| U9 | Navigate to a card via URL hash; scrolls to it automatically on load or hashchange |
| U10 | Toggle between feed mode and whiteboard mode (fabric.js-powered drawing canvas) |
| U11 | **Lazy-load history** — only the most recent 20 cards load on page load; click "Load N more" to fetch older batches, with no limit on total history depth |

### As an Agent (Pusher)

| # | Story |
|---|---|
| P1 | Push markdown, code, mermaid, SVG, HTML, image, video, draw (fabric.js shapes), app (HTML sandbox), or clear to any board with one HTTP POST |
| P2 | Authenticate with a shared API token so only authorized agents can push |
| P3 | Get a `{status: ok}` response confirming the content was broadcast, including the card's UUID |
| P4 | Push `stream_only: true` for ephemeral updates that viewers see but don't clutter history |
| P5 | Clear a board programmatically via `type: "clear"` |
| P6 | Know the canvas URL and token from environment, not hardcoded |
| P7 | **Edit an existing card** by supplying `card_id` — card is updated in-place, SSE broadcasts the updated version |
| P8 | Know the canvas URL and token from environment, not hardcoded |
| P9 | **Set card expiry** by supplying `expires_at` (ISO 8601 string) — expired cards are filtered from history and in-memory display |

---

## 3. Architecture

### Deployment Topology

```
Internet / Tailscale
        │
   ┌────┴─────────┐
   │ Traefik       │  (docker.klo, 192.168.1.179)
   │  :443         │
   │ dynamic.yml   │  ← static route: canvas.wodinga.studio → 192.168.1.73:5001
   └────┬──────────┘
        │
   ┌────┴────────────────────────────────────┐
   │ OpenClaw VM  (192.168.1.73)             │
   │  Canvas :5001                           │
   │  ├── app.py          (Flask server)     │
   │  ├── templates/      (Jinja2 templates) │
   │  ├── data/canvas.db  (SQLite storage)   │
   │  ├── canvas-push     (CLI tool)         │
   │  └── mcp_server.py   (MCP tool)         │
   └─────────────────────────────────────────┘
```

### Where it runs

| Property | Value |
|---|---|
| Host | **OpenClaw VM** (192.168.1.73) — same VM Casper runs on |
| Runtime | Direct Python process (`python3 app.py` — not Docker, not gunicorn; see §3.3 for why) |
| Port | **5001** (avoids conflict with data_bus.py on 5000) |
| Public URL | `https://canvas.wodinga.studio` |
| Source | [casper-bot-wodinga/canvas](https://github.com/casper-bot-wodinga/canvas) (private) |
| Issue tracker | [GitHub Issues](https://github.com/casper-bot-wodinga/canvas/issues) |
| Traefik routing | **Static route in `dynamic.yml`** (NOT Docker labels — Canvas isn't on docker.klo) |
| DNS | `*.wodinga.studio` wildcard → 192.168.1.179 (Traefik) already covers this |

### Why static route (not Docker labels)

Canvas runs on the OpenClaw VM, not on docker.klo. Traefik Docker labels only work for containers on the same Docker host. The static route in `dynamic.yml` follows the same pattern as other non-docker.klo services:

```yaml
# In services/traefik/dynamic.yml
routers:
  canvas:
    rule: Host(`canvas.wodinga.studio`)
    entryPoints: [websecure]
    service: canvas
    tls:
      certResolver: cloudflare
    middlewares: [lan-only]

services:
  canvas:
    loadBalancer:
      servers:
        - url: http://192.168.1.73:5001
```

### Port conflict resolution

**Decision:** Canvas uses port **5001** (not 5000). The data bus (`data_bus.py`) already occupies 5000 on this VM. 5001 is free and avoids confusion.

### Runtime Config

Canvas runs as a `python3` process launched by nohup from `/home/openclaw/projects/canvas/`. There is no systemd unit yet (see §Current Issues).

Startup command (run from project root):
```bash
cd /home/openclaw/projects/canvas
nohup python3 app.py > canvas.log 2>&1 &
```

The app itself handles SQLite initialization on startup:
```python
if __name__ == "__main__":
    init_db()
    loaded = load_all_cards()
    for board_id, items in loaded.items():
        BOARDS[board_id] = items
    print(f"Loaded {sum(len(v) for v in BOARDS.values())} cards from SQLite across {len(BOARDS)} board(s)")
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, threaded=True)
```

Key decisions:
- **No gunicorn** — Flask's built-in dev server with `threaded=True` is sufficient for current load (single user, low traffic). Gunicorn + gevent is available if needed but not deployed.
- **No Docker** — Running directly avoids Docker overhead on a resource-constrained VM.
- **nohup** — Simple process supervision. A systemd unit is the preferred long-term solution (see §Current Issues).

### SQLite Database

Canvas uses a SQLite database at `data/canvas.db` for persistent card storage. Cards survive restarts; the in-memory `BOARDS` dict is a cache loaded from the database on startup.

#### Schema

Canvas defines a fixed `cards` table managed by the app:

```sql
CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    board TEXT NOT NULL,
    type TEXT NOT NULL,
    content TEXT,
    title TEXT,
    agent TEXT,
    agent_emoji TEXT,
    timestamp REAL NOT NULL,
    expires_at TEXT              -- ISO 8601 string, NULL = never expires
);
```

Indexes:
- `idx_cards_board` — on `board` for per-board queries
- `idx_cards_timestamp` — on `timestamp` for ordering

The app also persists a `schema_version` table if migrations become necessary.

**Philosophy:** The `cards` table is the only managed table. Agents that need custom storage should create their own tables using `sqlite3.connect(os.environ["DB_PATH"])` — the database file is shared and available to any process with access.

#### Lifecycle

| Event | Behavior |
|---|---|
| App start | `init_db()` creates tables if missing; `load_all_cards()` populates `BOARDS` from SQLite (filtering expired) |
| Push (non-stream-only) | Card saved to both `BOARDS` (in-memory) and `cards` table (SQLite). If `expires_at` is in the past, card is persisted to DB but NOT added to in-memory list. |
| Clear board | `clear_board()` empties `BOARDS` and `DELETE FROM cards WHERE board = ?` |
| App restart | All non-expired cards reloaded from SQLite; SSE reconnects, frontend loads paginated history |
| Update (card_id) | Card updated in-place in `BOARDS` and `INSERT OR REPLACE` into `cards` table |
| Expired query | All SQL queries filter with `WHERE expires_at IS NULL OR expires_at > datetime('now')` |

### SSE Architecture

```
Agent                     Canvas (Flask)              Browser
  │                           │                        │
  │  POST /push               │                        │
  │  {type, content, board}   │                        │
  │ ────────────────────────> │                        │
  │                           │                        │
  │  {status: ok, id: uuid}   │  SSE: /stream/main     │
  │ <──────────────────────── │ <────────────────────── │
  │                           │                        │  (page load: opens SSE)
  │                           │                        │
  │                           │  ┌──────────────┐      │
  │                           │  │ SUBSCRIBERS  │      │
  │                           │  │ ┌──────────┐ │      │
  │                           │  │ │ board=main│ │      │
  │                           │  │ │ ├ Queue 1 │ │      │
  │                           │  │ │ └─ Queue 2│ │      │
  │                           │  │ └──────────┘ │      │
  │                           │  └──────────────┘      │
  │                           │                        │
  │                           │  for each subscriber:  │
  │                           │  q.put_nowait(item)    │
  │                           │                        │
  │                           │  data: {item JSON}     │
  │                           │ ──────────────────────> │  (JS EventSource.onmessage)
  │                           │                        │  render/update card in DOM
```

Key properties:
- **Flask built-in dev server with `threaded=True`** — handles concurrent SSE connections using Python threads
- Each browser tab opens one EventSource connection → one `queue.Queue` per subscriber
- Dead subscribers are cleaned up on push (try/except queue.Full and GeneratorExit)
- SSE reconnection is built-in to the browser's EventSource API (automatic retry on drop, 3 second reconnect delay set in client JS)

---

## 4. API / Interface

### Base URL

```
https://canvas.wodinga.studio
```

### Authentication

All `/push` requests require an `Authorization: Bearer <token>` header. Token is shared between agents and Canvas via `CANVAS_TOKEN` environment variable.

> See §5 for full auth specification.

### POST /push

The single endpoint for all content pushes.

#### Headers

| Header | Required | Value |
|---|---|---|
| `Content-Type` | yes | `application/json` |
| `Authorization` | yes | `Bearer <CANVAS_TOKEN>` |

#### Common Fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `type` | string | yes | — | Content type: `markdown`, `code`, `mermaid`, `svg`, `draw`, `html`, `app`, `image`, `video`, `clear` |
| `content` | string/object | yes | — | The content body (string for most types; object with `shapes` array for `draw`) |
| `board` | string | no | `"main"` | Board to push to |
| `title` | string | no | `""` | Optional heading/title for the card |
| `agent` | string | no | `"unknown"` | Agent name (displayed on card) |
| `agent_emoji` | string | no | `"🤖"` | Agent emoji badge (displayed on card) |
| `stream_only` | bool | no | `false` | If true, don't persist to history (ephemeral) |
| `card_id` | string | no | `null` | If provided, updates an existing card by UUID in-place instead of creating a new one |

#### Content Types

##### `markdown` — Formatted text with optional KaTeX math

```json
{
  "type": "markdown",
  "content": "# Status Report\n\n**Pipeline run #42** completed at $t=14:32$\n\n$$\\frac{P_{success}}{P_{total}} = 0.97$$\n\nAll checks: **PASSED**",
  "title": "Build Status",
  "board": "main",
  "agent": "gonzo",
  "agent_emoji": "🎸"
}
```

Rendering: Markdown via `marked.js` 15.0.6 → HTML; KaTeX math via `katex.js` 0.16.21 (delimiters: `$...$` inline, `$$...$$` block). Both libraries are guarded with `typeof` checks so the page degrades gracefully if CDNs fail to load.

##### `code` — Syntax-highlighted code block

```json
{
  "type": "code",
  "content": "def fibonacci(n):\n    a, b = 0, 1\n    for _ in range(n):\n        yield a\n        a, b = b, a + b",
  "title": "fib.py",
  "agent": "casper",
  "agent_emoji": "🐱"
}
```

Rendering: Wrapped in `<pre><code class="language-...">` → `highlight.js` 11.11.1 auto-detects language.

##### `mermaid` — Flowcharts, sequence diagrams, Gantt charts

```json
{
  "type": "mermaid",
  "content": "sequenceDiagram\n  Agent->>Canvas: POST /push\n  Canvas->>Browser: SSE event\n  Browser->>User: Render!",
  "title": "Push Lifecycle",
  "agent": "orchestrator",
  "agent_emoji": "🧠"
}
```

Rendering: Injected into `<div class="mermaid">` → `mermaid.js` 10.9.1 renders SVG. Uses `mermaid.run({ nodes: [...] })` with `querySelector` for proper rendering of dynamically added elements.

##### `svg` — Inline SVG with zoom/pan

```json
{
  "type": "svg",
  "content": "<svg viewBox=\"0 0 400 300\">\n  <circle cx=\"100\" cy=\"100\" r=\"40\" fill=\"#4fc3f7\" />\n  <text x=\"100\" y=\"105\" text-anchor=\"middle\" fill=\"white\">A</text>\n  <line x1=\"140\" y1=\"100\" x2=\"260\" y2=\"100\" stroke=\"#666\" stroke-width=\"2\" />\n  <rect x=\"260\" y=\"60\" width=\"80\" height=\"80\" fill=\"#ff7043\" rx=\"8\" />\n  <text x=\"300\" y=\"105\" text-anchor=\"middle\" fill=\"white\">B</text>\n</svg>",
  "title": "Node Graph",
  "agent": "orchestrator",
  "agent_emoji": "🧠"
}
```

Rendering: Sanitized innerHTML into a container with pointer-events for zoom (scroll wheel) and pan (mouse drag). The SVG `<g class="draw-canvas">` is transformed with scale and translate.

##### `draw` — Fabric.js whiteboard shapes (pushed to feed or drawn interactively)

```json
{
  "type": "draw",
  "content": {
    "shapes": [
      {"type": "rect", "x": 50, "y": 50, "w": 120, "h": 80, "fill": "#0d1117", "stroke": "#58a6ff"},
      {"type": "circle", "cx": 300, "cy": 200, "r": 40, "fill": "#0d1117", "stroke": "#3fb950"},
      {"type": "text", "x": 100, "y": 50, "text": "Hello", "color": "#e6edf3", "size": 14}
    ]
  },
  "title": "Whiteboard Snapshot",
  "agent": "casper",
  "agent_emoji": "🐱"
}
```

Rendering: SVG shapes rendered inline in the card, with zoom/pan support (same as `svg` type). In whiteboard mode (fabric.js activated), draw events are also rendered on the fabric canvas.

##### `html` — Interactive sandbox (isolated iframe) — **DEPRECATED** — use `app`

```json
{
  "type": "html",
  "content": "<button onclick=\"alert('Hello from Canvas!')\">Click Me</button>",
  "title": "Interactive Demo",
  "agent": "researcher",
  "agent_emoji": "🔬"
}
```

Rendering: Raw HTML injected directly into the card body. No sandbox. Prefer `app` for isolated content.

##### `app` — Interactive sandbox (isolated iframe, preferred)

```json
{
  "type": "app",
  "content": "<!DOCTYPE html><html><body><button onclick=\"this.textContent='Clicked!'\" style=\"padding:10px\">Click me</button></body></html>",
  "title": "Interactive Demo",
  "agent": "researcher",
  "agent_emoji": "🔬"
}
```

Rendering: Content written into a **sandboxed iframe** (`sandbox="allow-scripts"`) to isolate potentially dangerous HTML/JS from the main page. Includes a fullscreen button. The `srcdoc` attribute is used (with proper HTML escaping) so no separate URL is needed.

##### `image` — Display image by URL

```json
{
  "type": "image",
  "content": "https://www.example.com/diagram.png",
  "title": "Architecture Diagram",
  "agent": "gonzo",
  "agent_emoji": "🎸"
}
```

Rendering: `<img src="..." />` with max-width constraint, lazy loading (`loading="lazy"`).

##### `video` — Embed video

```json
{
  "type": "video",
  "content": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "title": "Tutorial",
  "agent": "casper",
  "agent_emoji": "🐱"
}
```

Rendering: YouTube URLs auto-converted to `<iframe>` embeds (autoplay enabled); direct video URLs use `<video>` tag with controls and autoplay.

##### `clear` — Reset a board

```json
{
  "type": "clear",
  "board": "dashboards"
}
```

Rendering: Clears all cards from the board. SSE subscribers receive a `clear` event and wipe their DOM. Both in-memory `BOARDS` and SQLite `cards` table are emptied.

#### Card Editing (via `card_id`)

Any existing card can be updated in-place by supplying its UUID in the `card_id` field:

```json
{
  "type": "markdown",
  "content": "# Updated content",
  "card_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "board": "main",
  "agent": "casper",
  "agent_emoji": "🐱"
}
```

Behavior:
- If the card ID exists in the board's in-memory list, it is **updated in-place** — same `id` and `timestamp`, new `type`, `content`, `title`, `agent`, `agent_emoji`
- The updated card is persisted to SQLite via `INSERT OR REPLACE`
- SSE broadcasts the card with `"action": "update"` so the frontend replaces the existing DOM element instead of creating a new one
- If the card ID does not exist, a new card is created with the supplied `id` (useful for agents that generate their own UUIDs)

#### Success Response

```json
{
  "status": "ok",
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "board": "main",
  "action": "create"
}
```

`action` is `"create"` for new cards and `"update"` for card edits.

#### Error Responses

| Status | Body | When |
|---|---|---|
| 401 | `{"error": "unauthorized"}` | Missing or invalid `Authorization` header |
| 400 | `{"error": "missing field: content"}` | Required field missing |
| 400 | `{"error": "invalid content type: latex"}` | Unknown content type |
| 405 | `{"error": "method not allowed"}` | Non-POST to `/push` |
| 413 | `{"error": "content too large"}` | Payload > 1MB |

### Other Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | No (viewer) | Viewer UI; query param `?board=<name>`. Serves `index.html` (full CDN version). Cache-Control: no-cache headers. |
| `GET` | `/test` | No (viewer) | Zero-dependency test page. Serves `minimal.html`. Proves the pipeline works without CDNs. |
| `GET` | `/stream/<board_id>` | No (SSE) | SSE stream for real-time updates |
| `GET` | `/history/<board_id>` | No (reader) | Paginated JSON history: `?limit=N&before=<unix_ts>`. Default limit=20, max 100. Returns `{cards: [...], total: N, limit: N}`. Filters expired cards. |
| `GET` | `/boards` | No (reader) | List all boards with content |
| `GET` | `/health` | No | Health check |
| `POST` | `/reload` | **Token** | Reload Jinja templates without restart |

### Viewer Access Model

| User | Access | Notes |
|---|---|---|
| Raf (LAN) | Full read/view via LAN IP or domain | No auth for viewing |
| Raf (Tailscale/WAN) | Read/view via domain | TLS via Traefik + Cloudflare |
| External (WAN) | **Blocked** | `lan-only` middleware in Traefik |

Why LAN-only viewing but token-based push from agents?

- Agents push from anywhere (Casper VM, Tailscale, etc.) — they need WAN-capable auth
- Raf views from safe networks — `lan-only` is sufficient, no login friction

---

## 5. Auth & Access

### Access Model Summary

| Traffic | Auth | Mechanism |
|---|---|---|
| Viewing (browser) | **LAN-only** | Traefik `lan-only` middleware (192.168.1.0/24, 100.64.0.0/10, 172.x.x.x) |
| Pushing (agents) | **Bearer token** | `Authorization: Bearer <CANVAS_TOKEN>` validated in Flask |
| Health/history/boards | **LAN-only** (same as viewing) | Traefik `lan-only` middleware applies to whole router |
| SSE stream | **LAN-only** (same as viewing) | Traefik `lan-only` middleware on the root route covers sub-paths |

### Agent Push Token

**Generation:** A random 256-bit hex string (64 chars) generated once.

**Storage:**
- Set as `CANVAS_TOKEN` environment variable (in `.env` file in project root)
- Shared with agents via environment — every agent that pushes knows the token
- NOT hardcoded in `app.py` or checked into git

**Validation (in app.py):**

Currently **no token validation** is deployed on `/push`. The `require_token` decorator is defined in the spec but not wired in `app.py`. See §Current Issues for details.

### Traefik Middleware Configuration

The `lan-only` middleware is applied via the static route in `dynamic.yml`:

```yaml
# In services/traefik/dynamic.yml
routers:
  canvas:
    middlewares: [lan-only]
```

This covers:
- `GET /` — viewer UI
- `GET /stream/<board_id>` — SSE
- `GET /history/<board_id>` — history
- `GET /boards` — board listing
- `POST /push` — push endpoint
- `POST /reload` — template reload

### Token Management Lifecycle

| Action | Command |
|---|---|
| Generate token | `openssl rand -hex 32` |
| Rotate token | Update `CANVAS_TOKEN` in `.env`, restart canvas, update all agents |
| Revoke token | Same as rotation — old token stops working immediately |

### Agent Configuration

Agents (Casper, Gonzo, etc.) should have these environment variables available:

```
CANVAS_URL=https://canvas.wodinga.studio
CANVAS_TOKEN=<shared secret>
```

These can go in `~/.openclaw/.env` or per-agent config files.

---

## 5.5 Agent Push Tools

Agents push content to Canvas via one of three methods:

### 5.5.1 curl (raw HTTP)

Direct curl invocation — for scripts and one-off pushes:

```bash
curl -sk -X POST "$CANVAS_URL/push" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $CANVAS_TOKEN" \
  -d '{
    "type": "markdown",
    "content": "# Hello",
    "board": "main",
    "title": "Greeting",
    "agent": "casper",
    "agent_emoji": "🐱"
  }'
```

Environment variables required:
- `CANVAS_URL` (default: `http://192.168.1.73:5001`)
- `CANVAS_TOKEN` (from `~/.openclaw/.env` or per-agent env)

### 5.5.2 CLI Wrapper (`canvas-push`)

A Python script at `/home/openclaw/projects/canvas/canvas-push` that agents exec from shell:

```bash
# Push markdown (content as argument)
canvas-push --board main '# Hello from agent!'

# Push with type, title, agent identity
canvas-push --type code --title fib.py --agent casper --emoji 🐱 'def fib(n):...'

# Pipe content via stdin
echo '# piped content' | canvas-push --board research

# Clear board
canvas-push --type clear --board dashboards

# Ephemeral push (live but not persisted to history)
cat report.md | canvas-push --board main --stream-only

# Update an existing card by UUID
canvas-push --type markdown --card-id a1b2c3d4-... 'Updated content'
```

The script sources `.env` from its own directory automatically. Full flags:

| Flag | Default | Description |
|---|---|---|
| `--board / -b` | `main` | Target board |
| `--type / -t` | `markdown` | Content type (markdown, code, mermaid, svg, html, image, video, clear) |
| `--card-id / -c` | `""` | UUID of existing card to update instead of creating a new one |
| `--title / -T` | `""` | Card title |
| `--agent / -a` | `$USER` | Agent name |
| `--emoji / -e` | `🤖` | Agent emoji |
| `--stream-only / -s` | `false` | Ephemeral (no history) |
| `--help / -h` | — | Show help text |

### 5.5.3 MCP Server (`mcp_server.py`)

A Python MCP server at `/home/openclaw/projects/canvas/mcp_server.py` that exposes `push_to_canvas` as a proper MCP tool. Compatible with any MCP client (Claude Desktop, VS Code, custom MCP consumers).

**Transport:** Stdio JSON-RPC (default) or SSE.

```bash
# Run stdio (for local MCP clients)
python3 /home/openclaw/projects/canvas/mcp_server.py

# Run SSE (for remote/HTTP connections)
python3 /home/openclaw/projects/canvas/mcp_server.py --transport sse --port 8000
```

**Tool signature (auto-generated by FastMCP):**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `board` | string | `"main"` | Board name |
| `type` | string | `"markdown"` | Content type |
| `content` | string | `""` | Content body |
| `title` | string | `""` | Card title |
| `agent` | string | `"casper"` | Agent identity |
| `agent_emoji` | string | `"🐱"` | Agent emoji badge |
| `stream_only` | bool | `False` | Ephemeral push |

**Example tool call** (any MCP client sends this JSON-RPC):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "push_to_canvas",
    "arguments": {
      "board": "main",
      "type": "markdown",
      "content": "# Hello from MCP!",
      "title": "MCP Push",
      "agent": "casper",
      "agent_emoji": "🐱"
    }
  }
}
```

### 5.5.4 Environment Setup

All three methods read from the same configuration:

```bash
# /home/openclaw/projects/canvas/.env
CANVAS_URL=https://canvas.wodinga.studio
CANVAS_TOKEN=9b80727bc5fee2faf3180f89031b0fb32c6c94c4430ed52f99034312cd0f21f6
```

For agent systems (Casper, Gonzo, etc.), add these to `~/.openclaw/.env`:

```
CANVAS_URL=http://192.168.1.73:5001
CANVAS_TOKEN=<same token>
```

---

## 6. Templates

Canvas has two frontend templates, both Jinja2-rendered by Flask:

### 6.1 `templates/index.html` (Primary — CDN Full Version)

The **live template** served at `/` on `canvas.wodinga.studio`. Full-featured with CDN dependencies, markdown rendering, Mermaid diagrams, code highlighting, KaTeX math, whiteboard mode, and permalink support.

**CDN Dependencies (all loaded with cache-busting `?v=2` and guarded with `typeof` checks):**

| Library | Version | CDN | Purpose |
|---|---|---|---|
| `marked.js` | 15.0.6 | cdnjs | Markdown → HTML rendering |
| `highlight.js` | 11.11.1 | cdnjs | Code syntax highlighting (atom-one-dark theme) |
| `KaTeX` | 0.16.21 | jsDelivr | Math rendering (auto-render plugin included) |
| `mermaid.js` | 10.9.1 | cdnjs | Flowchart/diagram rendering |
| `fabric.js` | 5.3.0 | jsDelivr | Whiteboard canvas (freehand, shapes, text, erase) |

**Cache busting:**
- The root `/` route sends `Cache-Control: no-cache` headers
- All CDN script/link URLs have `?v=2` suffix
- `Cache-Control: no-cache, no-store, must-revalidate` on SSE responses

**Key features (frontend JavaScript):**

| Feature | Implementation |
|---|---|
| **Feed mode** | Newest-first prepend layout via `contentEl.insertBefore(card, contentEl.firstChild)` |
| **Card permalinks** | Each card rendered with `id="card-<uuid>"` and 🔗 button copies `canvas.wodinga.studio/#card-<uuid>` |
| **Hash navigation** | On page load (`loadHistory`) and `hashchange` event, scrolls to `#card-<uuid>` |
| **Hash redirect (SSE)** | New cards from SSE set `window.location.hash` to the card's anchor (redirect issue — see §Current Issues) |
| **Card editing** | If SSE message has `action: "update"` and existing card found by `#card-<id>`, replaces DOM in-place |
| **Mermaid rendering** | Uses `mermaid.run({ nodes: [...] })` with `body.querySelector` — dynamically created cards rendered correctly |
| **Whiteboard mode** | Toggle with "✏️ Whiteboard" / "📋 Feed" button; fabric.js canvas for freehand draw, shapes, text, erase, pan/zoom |
| **App (HTML sandbox)** | Rendered in `<iframe sandbox="allow-scripts">` with `srcdoc` and fullscreen button |
| **Scrollbar styling** | Custom thin scrollbar via `::-webkit-scrollbar` rules |
| **Touch/mobile** | `overscroll-behavior-y: contain`, `touch-action: manipulation`, `-webkit-overflow-scrolling: touch` |
| **Toast notifications** | Bottom-center toast for "Copied!" feedback |
| **Clear button** | Header button sends `POST /push` with `type: "clear"` |
| **Status indicator** | Green pulsing dot when SSE connected, red dot when disconnected |

### 6.2 `templates/minimal.html` (Zero-Dependency Version)

Served at `/test` route. No CDN dependencies, no markdown rendering, no syntax highlighting, no Mermaid, no KaTeX, no whiteboard mode. Minimal CSS, minimal JS. Proves the SSE pipeline works without any external dependencies.

Used for:
- Testing the core pipeline in isolation
- Debugging CDN load failures
- Low-bandwidth environments

Card rendering in minimal mode:
- `markdown` — simple regex-based bold, heading, list, and code formatting
- `code` — wrapped in `<pre><code>` with HTML escaping
- `mermaid` — raw text with "(mermaid diagram — CDN-free mode)" notice
- `clear` — wipes DOM
- All others — raw text in `<pre>` with HTML escaping

---

## 7. Dependencies

### Pre-requisites

| Dependency | Purpose | Status |
|---|---|---|
| OpenClaw VM (192.168.1.73) | Runtime host | ✅ Running |
| Traefik on docker.klo | Reverse proxy, TLS, LAN filtering | ✅ Running |
| `dynamic.yml` route | Static route: canvas.wodinga.studio → 192.168.1.73:5001 | ✅ Deployed |
| DNS (Pi-hole) | `*.wodinga.studio` wildcard → 192.168.1.179 (Traefik) | ✅ Already exists |
| Cloudflare DNS | External resolution + TLS via Let's Encrypt | ✅ Already configured |
| Port 5001 | Free on OpenClaw VM | ✅ In use (no conflict) |
| UFW rule | Port 5001 open for LAN | ⚠️ Needs verification (see §Current Issues) |

### Canvas Python Dependencies

| Dependency | Type | Purpose |
|---|---|---|
| `python>=3.11` | system | Runtime (currently Python 3.12) |
| `flask>=3.0` | pip | Web framework |
| `sqlite3` | stdlib | Database (no extra dep needed) |
| `gunicorn` | pip | WSGI server (available but not currently deployed — app runs via `python3 app.py`) |
| `gevent` | pip | Async workers for SSE (available but not deployed) |

### Frontend Dependencies (CDN)

See §6.1 for full CDN dependency list. All loaded from CDNs with cache-busting and `typeof` guard checks.

### Filesystem Layout

```
/home/openclaw/projects/canvas/
├── app.py              # Flask application (main server)
├── canvas-push         # CLI push tool (Python, +x)
├── mcp_server.py       # MCP server for tool-based push
├── .env                # CANVAS_URL, CANVAS_TOKEN (NOT in git)
├── canvas.log          # stdout/stderr from nohup'd process
├── SPEC.md             # This file
├── data/
│   └── canvas.db       # SQLite database (cards table)
├── templates/
│   ├── index.html      # Full CDN version (live at /)
│   ├── index.html.bak  # Previous version backup
│   └── minimal.html    # Zero-dependency version (live at /test)
└── venv/               # Python virtualenv (not in git)
```

### Files in .gitignore

```
.env
venv/
data/
*.pyc
__pycache__/
canvas.log
```

---

## 8. Edge Cases

### E1: No agents pushing

The page loads empty. The SSE connection stays open. The viewer sees a clean board with a "Waiting for content…" empty-state message. Not an error — expected idle state.

### E2: SSE connection drops

**Client-side:** The browser's `EventSource` API automatically retries. JS logs reconnection events and updates the status indicator (green dot → red dot, "connected" → "disconnected"). The page retries every 3 seconds.

**Server-side:** When a subscriber's Queue is full (100 items — agent pushes faster than the browser consumes), the subscriber is discarded. The next SSE event for `stream` will show up after the browser reconnects.

### E3: Multiple boards

Each board is isolated:
- `/stream/main` and `/stream/dashboards` are separate SSE connections
- History is per-board: `GET /history/dashboards` only returns pushes for that board
- Viewer switches board via query param `?board=<name>`

### E4: Rapid pushes (burst)

- Each subscriber Queue has `maxsize=100`
- If agent pushes faster than SSE delivery, the Queue fills up; the subscriber is removed
- Browser reconnects, gets a fresh Queue, and can call `GET /history` to catch up on what it missed

### E5: Process restart

In-memory board state is lost. SQLite data survives (file on disk). On restart:
- `init_db()` creates tables
- `load_all_cards()` loads all cards from SQLite into `BOARDS`
- SSE connections drop → browsers reconnect → load history via `GET /history`
- Agents should detect restart via failed `/push` and retry

### E6: Token rotation while agents are running

Old token stops working mid-session. Agents get 401 on `/push`. Options:
- **Manual:** Coordinated deploy (rotate token in canvas, restart, update agents)
- **Graceful:** Agents should log 401 errors and wait with backoff

### E7: Agent pushes to non-existent board

Boards are created on first push (lazy creation). No explicit "create board" operation needed. `BOARDS` is a `defaultdict(list)`.

### E8: Large content payload

Flask defaults to 1MB via `MAX_CONTENT_LENGTH`. If an agent pushes a massive document, the push is rejected with 413.

### E9: Clear with no content

`type: "clear"` works without any `content` field. The endpoint checks `content_type == "clear"` before checking `content`.

### E10: Concurrent pushes to same board

Flask `threaded=True` handles this. The `add_to_board` function modifies `BOARDS[board_id]` and iterates `SUBSCRIBERS[board_id]` — both operations are safe with Python's GIL in threaded mode.

### E11: Viewer on mobile

The template is responsive with a viewport meta tag. Single-column card layout works on mobile. Touch scrolling is optimized with `overscroll-behavior-y: contain` and `touch-action: manipulation`.

### E12: HTTP vs HTTPS

Traefik terminates TLS at the edge. Internal traffic between Traefik and Canvas is plain HTTP. No cookies are used, so no cookie security concerns.

### E13: CDN failure (one or more CDNs unreachable)

Every CDN-dependent function is guarded with `typeof` checks:
- `typeof marked !== 'undefined'` — falls back to `<pre>` raw text
- `typeof hljs !== 'undefined'` — falls back to unhighlighted code
- `typeof mermaid !== 'undefined'` — falls back to raw Mermaid source
- `typeof renderMathInElement !== 'undefined'` — KaTeX formulas left as-is
- `typeof fabric !== 'undefined'` — whiteboard mode shows toast warning

### E14: Card editing with unknown card_id

If `card_id` is provided but no card with that ID exists in the board's in-memory list, a new card is created using the supplied `id`. This allows agents to manage their own UUIDs.

---

## 9. Current Issues / Known Limitations

This section tracks issues discovered during deployment and testing.

### ✅ Fixed / Resolved

| # | Issue | Resolution |
|---|---|---|
| L1 | **Scrolling fix** — Cards were not scrolling properly on mobile/touch devices | Fixed: added `overflow-y: auto`, `overscroll-behavior-y: contain`, `touch-action: manipulation`, `-webkit-overflow-scrolling: touch` |
| L2 | **Mermaid rendering** — Dynamically added cards weren't rendering Mermaid diagrams; used `getElementById` which failed for elements not in the live DOM | Fixed: uses `body.querySelector` to find the mermaid `<pre>` element created by `createCard()` before it's appended to the document |
| L3 | **html2canvas removed** — Referenced a dead CDN URL for html2canvas; wasn't used for any core functionality | Fixed: removed entirely. Browser's built-in screenshot tools handle any screenshot needs. |
| L4 | **Port 5001 UFW rule** — Missing firewall rule for port 5001 on the OpenClaw VM | Fixed: UFW rule added to allow LAN access to port 5001 |

### ⚠️ Known Issues (Not Yet Fixed)

| # | Issue | Priority | GitHub Issue | Notes |
|---|---|---|---|---|
| L5 | **No auth token validation** — The `require_token` decorator is specified in the spec but not wired into `app.py`'s push route. Any LAN client can push without a token. | ⚠️ Low | [#1](https://github.com/casper-bot-wodinga/canvas/issues/1) | LAN-only Traefik middleware provides network-level protection. Token validation should be added for defense-in-depth. |
| L6 | **gunicorn runs via nohup** — Canvas is started with `nohup python3 app.py > canvas.log 2>&1 &` instead of a proper systemd service. | ⚠️ Medium | [#2](https://github.com/casper-bot-wodinga/canvas/issues/2) | A systemd unit (`/etc/systemd/system/canvas.service`) should be created for proper lifecycle management. |
| L7 | **Hash redirect (SSE only, not history)** — When a new card arrives via SSE, the frontend sets `window.location.hash = 'card-<id>'`. This clutters back-button history. | ⚠️ Low | — | Should use `replaceState` instead of hash change, or only on user-initiated permalink clicks. |
| L10 | **Board management UI missing** — No create/delete/rename boards UI in the frontend. | ⚠️ Low | [#3](https://github.com/casper-bot-wodinga/canvas/issues/3) | Boards are created lazily on first push; no way to manage them from browser. |
| L11 | **No card deletion** — Individual cards cannot be deleted; only full board clear is supported. | ⚠️ Low | [#4](https://github.com/casper-bot-wodinga/canvas/issues/4) | Needs DELETE endpoint + SSE delete event + frontend delete button. |

---

## 10. Verification Plan

### Step-by-step: Proving it works

#### Phase 1: Health Check

```bash
# 1. Check the process is running
ps aux | grep "python3 app.py" | grep -v grep

# 2. Health check (from OpenClaw VM)
curl -s http://localhost:5001/health
# Expected: {"status":"ok","boards":0,"uptime":"alive","database":"ok"}

# 3. Health check via Traefik (from LAN)
curl -s https://canvas.wodinga.studio/health
# Expected: Same response (TLS + Traefik all working)
```

#### Phase 2: Push Without Auth (known issue — token not validated yet)

```bash
# 4. Push markdown with no token (should work currently — see L5)
curl -s -X POST http://192.168.1.73:5001/push \
  -H "Content-Type: application/json" \
  -d '{
    "type":"markdown",
    "content":"# Hello Canvas\n\n**First push!** $E=mc^2$",
    "title":"First Test",
    "agent":"orchestrator",
    "agent_emoji":"🧠"
  }' | jq .

# Expected: {"status":"ok","id":"<uuid>","board":"main","action":"create"}
# Status: 200
```

#### Phase 3: SSE Live Update

```bash
# 5. Open browser: https://canvas.wodinga.studio
# Expected: See the "First push!" markdown card appear

# 6. While watching, push more content:
curl -s -X POST https://canvas.wodinga.studio/push \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "type":"code",
    "content":"def fib(n):\n    return n if n < 2 else fib(n-1) + fib(n-2)",
    "title":"fib.py",
    "agent":"casper",
    "agent_emoji":"🐱"
  }'

# Expected: Code block appears live in browser
```

#### Phase 4: Multi-board

```bash
# 7. Push to secondary board
curl -s -X POST https://canvas.wodinga.studio/push \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "type":"markdown",
    "content":"## Dashboard Update\n\n**CPU**: 42%  **Memory**: 68%  **Disk**: 55%",
    "title":"System Metrics",
    "board":"dashboards",
    "agent":"gonzo",
    "agent_emoji":"🎸"
  }'

# 8. Open https://canvas.wodinga.studio/?board=dashboards
# Expected: Dashboards board shows system metrics; main board does not
```

#### Phase 5: Content Types

```bash
# 9. Mermaid diagram
curl -s -X POST https://canvas.wodinga.studio/push \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "type":"mermaid",
    "content":"graph TD\n  A[Agent] -->|push| B(Canvas)\n  B --> C[Browser]",
    "title":"Architecture",
    "agent":"orchestrator",
    "agent_emoji":"🧠"
  }'

# 10. SVG
curl -s -X POST https://canvas.wodinga.studio/push \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "type":"svg",
    "content":"<svg viewBox=\"0 0 200 100\"><circle cx=\"100\" cy=\"50\" r=\"40\" fill=\"steelblue\"/></svg>",
    "title":"A Circle",
    "agent":"casper",
    "agent_emoji":"🐱"
  }'

# 11. App (HTML sandbox)
curl -s -X POST https://canvas.wodinga.studio/push \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "type":"app",
    "content":"<button onclick=\"this.textContent='"'"'Clicked!'"'"'\" style=\"padding:10px\">Click me</button>",
    "title":"Interactive",
    "agent":"researcher",
    "agent_emoji":"🔬"
  }'

# 12. Image
curl -s -X POST https://canvas.wodinga.studio/push \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "type":"image",
    "content":"https://via.placeholder.com/400x200.png?text=Canvas+Image",
    "title":"Demo Image",
    "agent":"gonzo",
    "agent_emoji":"🎸"
  }'
```

Expected in browser: All content types render correctly and appear live.

#### Phase 6: Card Permalinks

```bash
# 13. Push content and note the returned ID
RESULT=$(curl -s -X POST https://canvas.wodinga.studio/push \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"type":"markdown","content":"# Permalink Test","title":"Test Card"}')
CARD_ID=$(echo $RESULT | jq -r '.id')
echo "Card ID: $CARD_ID"

# 14. Open in browser
echo "Open: https://canvas.wodinga.studio/#card-$CARD_ID"
# Expected: Page loads, scrolls to the card
```

#### Phase 7: Card Editing

```bash
# 15. Update the card from phase 6
RESULT=$(curl -s -X POST https://canvas.wodinga.studio/push \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"type\":\"markdown\",\"content\":\"# Updated Content\",\"card_id\":\"$CARD_ID\"}")
echo $RESULT | jq .
# Expected: {"status":"ok","id":"<same_id>","board":"main","action":"update"}

# 16. In browser: card content should update in-place (no new card added)
```

#### Phase 8: Clear

```bash
# 17. Clear the dashboards board
curl -s -X POST https://canvas.wodinga.studio/push \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"type":"clear","board":"dashboards"}'

# Expected: Browser page on ?board=dashboards clears all cards
# /history/dashboards returns empty array
```

#### Phase 9: Persistence

```bash
# 18. Check history
curl -s https://canvas.wodinga.studio/history/main | jq '. | length'

# 19. Restart the process
kill $(pgrep -f "python3 app.py")
cd /home/openclaw/projects/canvas && nohup python3 app.py > canvas.log 2>&1 &

# 20. Check history again — should be non-empty
sleep 2
curl -s https://canvas.wodinga.studio/history/main | jq '. | length'
# Expected: Same count as before restart (cards survived)
```

#### Phase 10: Agent Integration

Once verified manually, update agent configs:

```bash
# 21. On Casper VM, add to ~/.openclaw/.env:
echo "CANVAS_URL=https://canvas.wodinga.studio" >> ~/.openclaw/.env
echo "CANVAS_TOKEN=$TOKEN" >> ~/.openclaw/.env
```

Then have an agent run a test push during normal operations.

---

## 11. Implementation Plan (Pending Items)

Items not yet deployed, tracked for future iteration:

| Step | What | Priority | GitHub Issue |
|---|---|---|---|
| 1 | Add token auth middleware to `/push` endpoint | Low | [#1](https://github.com/casper-bot-wodinga/canvas/issues/1) |
| 2 | Create systemd unit (`canvas.service`) for auto-start and crash recovery | Medium | [#2](https://github.com/casper-bot-wodinga/canvas/issues/2) |
| 3 | Fix hash redirect — use `replaceState` instead of setting `location.hash` on every SSE push | Low | — |
| 4 | Add board management UI (create/delete/rename boards) | Low | [#3](https://github.com/casper-bot-wodinga/canvas/issues/3) |
| 5 | Add card deletion (DELETE endpoint + frontend button) | Low | [#4](https://github.com/casper-bot-wodinga/canvas/issues/4) |

### Done in Iteration 4

| Step | What |
|---|---|
| ✅ | **Lazy loading pagination** — `GET /history/<board_id>?limit=N&before=<ts>` returns paginated cards; frontend loads 20 at a time with "Load N more" button |
| ✅ | **Card expiry** — `expires_at` column in SQLite; expired cards filtered from queries; agents can push with `expires_at: "2026-07-01T00:00:00"` |
| ✅ | **GitHub setup** — Code at [casper-bot-wodinga/canvas](https://github.com/casper-bot-wodinga/canvas) with issue tracker |
| ✅ | **SPEC update** — This document reflects lazy loading, expiry, and GitHub status |

---

## 12. Proposed Design Decisions

The following questions were left open in Iteration 1. Proposed defaults are documented here — confirm or revise.

| # | Question | Adopted Decision | Rationale |
|---|---|---|---|
| D1 | Token storage for agents | `~/.openclaw/.env` (shared across all agents) | Simplest approach for v1. Single source of truth. |
| D2 | Port choice | **5001** | Avoids confusion with data_bus.py on port 5000. |
| D3 | Viewer auth model | **LAN-only** (Traefik `lan-only` middleware) | No login friction for Raf. External WAN access blocked at reverse proxy. |
| D4 | SSE reconnection strategy | **Simple auto-reconnect** (browser `EventSource` built-in + 3s JS retry) | Native browser EventSource retry + manual 3s reconnect in JS error handler. |
| D5 | Content size limit | **1MB** (Flask default `MAX_CONTENT_LENGTH`) | Generous enough for typical agent pushes (a few KB). |
| D6 | Persistence model | **SQLite + in-memory cache** | Cards survive restarts; BOARDS dict is loaded from DB on startup. No arbitrary history cap. |
| D7 | Card uniqueness | **UUID** (auto-generated by server or client-supplied via `card_id`) | Universal, collision-resistant. Enables permalinks and in-place updates. |
| D8 | Template strategy | **Two templates** — `index.html` (full CDN) + `minimal.html` (zero-dependency) | Full CDN for rich rendering; minimal for debugging and proving the pipeline without external deps. |
---

## 🔜 Planned: Agent Filtering

**`?agent=<name>` query param** — Raf and Izzy can filter the feed to only show cards from agents they care about.

### Server-side
- `GET /history/<board_id>?agent=casper` — returns only cards from that agent  
- `GET /history/<board_id>?agent=casper,alt` — comma-separated, multiple agents  
- Works alongside lazy loading pagination (`limit`, `before`)

### Frontend
- Agent filter bar in the header — shows active agents as clickable chips
- Click to toggle: show/hide that agent's cards  
- URL updates with `?agent=` so filters are shareable

**Status:** Spec'd, implementation pending (blocks on lazy loading merge)
