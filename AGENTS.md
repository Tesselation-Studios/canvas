# Canvas — Agent Instructions

**Canvas is Raf's real-time visual whiteboard.** Agents push content, Raf watches it render live. Think: shared dashboard for an AI+human team.

**URL:** `https://canvas.wodinga.studio`
**Repo:** `casper-bot-wodinga/canvas` (private)

## How to push

### Quick push (CLI)
```bash
/home/openclaw/projects/canvas/canvas-push --board main --type markdown --title "Hello" --agent hermes --emoji 🧠 "Content here"
echo "piped markdown" | /home/openclaw/projects/canvas/canvas-push --type code --title script.py
```

### Direct API
```bash
curl -sk -X POST "$CANVAS_URL/push" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $CANVAS_TOKEN" \
  -d '{"type":"markdown","content":"Hello","board":"main","agent":"hermes","agent_emoji":"🧠"}'
```

### Update a card in-place
```bash
/home/openclaw/projects/canvas/canvas-push --card-id <uuid> --type markdown "Updated content"
```

## Content types
- `markdown` — formatted text (default)
- `code` — syntax-highlighted code block
- `mermaid` — flowcharts, diagrams
- `html` — interactive sandbox (iframe)
- `draw` — SVG shapes
- `image` — image by URL
- `video` — video embed or YouTube
- `clear` — wipe a board

## Boards
Default is "main". Use `--board <name>` for separate boards. Boards are created on first push.

## Rules
- **Spec is the source of truth** — SPEC.md defines what Canvas IS. Code matches spec, not the other way around. To change behavior: update SPEC.md first, get approval, THEN write code.
- **Never commit the token** — it lives in `.env` (gitignored)
- **Use `--card-id` to iterate** — update an existing card instead of flooding the board
- **Boards are for themes** — use `--board research`, `--board coding`, etc. for organization
- **Expiry defaults to 1 year** — pass `"expires_at": null` for immortal cards
- **This repo is private** — don't expose the URL or token

## Auth
Source `CANVAS_URL` and `CANVAS_TOKEN` from the project `.env` file or your agent's environment.

## Skill Auto-Update
Before acting on this repo, check whether this skill file (SKILL.md) is newer than your local copy. If the repo version is newer, copy it to your local skill directory first:

```bash
# Check file modification times
repo_skill="/home/openclaw/projects/canvas/SKILL.md"
local_skill="/home/openclaw/.openclaw/workspace/skills/canvas/SKILL.md"
if [ -f "$local_skill" ] && [ "$repo_skill" -nt "$local_skill" ]; then
    echo "[canvas] Repo SKILL.md is newer — updating local copy..."
    cp "$repo_skill" "$local_skill"
fi
```

This keeps agent behavior in sync with the repo's latest instructions. Check this on every repo interaction, not just the first one.

> **Note:** If your local skill directory path differs, adjust `local_skill` accordingly.
