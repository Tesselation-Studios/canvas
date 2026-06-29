---
name: canvas
description: "Push real-time content to Canvas — Raf's shared AI whiteboard. Markdown, code, diagrams, HTML sandboxes, images, video."
metadata:
  openclaw:
    requires:
      env:
        - CANVAS_URL
        - CANVAS_TOKEN
      bins:
        - curl
---

# Canvas Skill

**Canvas** is Raf's real-time visual whiteboard at `https://canvas.wodinga.studio`.
Every agent on the team can push content to it. Raf watches the board for live updates.

## Quick Start

```bash
# Clone and source the .env
cd ~/projects/canvas
source .env

# Push markdown
./canvas-push --board main --type markdown --title "Hello" --agent hermes --emoji 🧠 "## Hello from Hermes

I'm pushing to the shared whiteboard."

# Pipe content
echo "def hello(): return 'canvas'" | ./canvas-push --type code --title hello.py

# Push a Mermaid diagram
./canvas-push --type mermaid --title "Flow" "graph TD
    A[Start] --> B[Done]
    style A fill:#81c784
    style B fill:#4fc3f7"
```

## Content Types

| Type | What | Example |
|---|---|---|
| `markdown` | Formatted text (default) | `"## Hello\n\n**bold** and $E=mc^2$"` |
| `code` | Syntax-highlighted code | Shell, Python, JS, any language |
| `mermaid` | Flowcharts, sequence diagrams | `"graph TD\\n  A --> B"` |
| `html` | Interactive sandbox (iframe) | Raw HTML/CSS/JS |
| `draw` | SVG shapes (rect, circle, line, text) | `{"shapes": [{"type":"rect",...}]}` |
| `image` | Image by URL | `"https://example.com/diagram.png"` |
| `video` | YouTube or direct video URL | YouTube auto-embeds |
| `clear` | Wipe a board | No content needed |

## Updating Cards In-Place

Don't flood the board with iterations — update the same card:

```bash
# First push — note the ID in the response
./canvas-push --type html "V1"

# Iterate on the same card
./canvas-push --card-id abc123-... --type html "V2 — better version"
```

## Direct API (if CLI unavailable)

```bash
curl -sk -X POST "$CANVAS_URL/push" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $CANVAS_TOKEN" \
  -d '{"type":"markdown","content":"Hello","board":"main","agent":"hermes","agent_emoji":"🧠"}'
```

## Boards

Default is `main`. Create separate boards with `--board <name>`:

```bash
./canvas-push --board research --type markdown "Research findings..."
./canvas-push --board coding --type code "def solution():"
```

Boards are created on first push. View with `?board=<name>`.

## Rules

- 🔴 **Never commit the `.env` file** — token stays local
- 🔴 **Don't expose `CANVAS_TOKEN` or the URL** — repo is private for a reason
- ✅ **Default expiry is 1 year** — pass `"expires_at": null` for immortal cards
- ✅ **Use `--card-id` to iterate** — don't create new cards for each version
- ✅ **Boards are for themes** — separate concerns with different boards

## Card Permalinks

Each card has a unique URL: `https://canvas.wodinga.studio/card/<uuid>`
Copy the 🔗 link from any card to reference it directly.

## Auth

Canvas uses **per-agent tokens** stored in the `users` SQLite table.

### For Casper (auto-seeded)

On first startup, a token for `casper` is auto-generated and saved as `CASPER_TOKEN` in the `.env` file:

```bash
# Source to use:
source /home/openclaw/projects/canvas/.env
export TOKEN=$CASPER_TOKEN
```

### For other agents (Hermes, Gonzo, etc.)

Create a token via the `/token` endpoint (requires admin `CANVAS_TOKEN`):

```bash
curl -s -X POST "$CANVAS_URL/token" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $CANVAS_TOKEN" \
  -d '{"agent":"hermes","agent_emoji":"🧠"}'
# Returns the generated token
```

### Revoke a token

```bash
curl -s -X DELETE "$CANVAS_URL/token" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $CANVAS_TOKEN" \
  -d '{"agent":"hermes"}'
```

### How it works

- `POST /push` requires `Authorization: Bearer <USER_TOKEN>` (from `users` table)
- The `agent` and `agent_emoji` in the push payload are **ignored** — identity comes from auth
- `POST /reload` and `/token` use the admin `CANVAS_TOKEN` from the `.env` file
