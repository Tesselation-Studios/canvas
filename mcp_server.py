#!/usr/bin/env python3
"""
Canvas MCP Server — exposes push_to_canvas as a tool via the Model Context Protocol.

Run (stdio transport — for MCP clients like Claude Desktop, VS Code, etc.):
  python3 /home/openclaw/projects/canvas/mcp_server.py

Run (SSE transport — for remote connections):
  python3 /home/openclaw/projects/canvas/mcp_server.py --transport sse --port 8000

Environment:
  CANVAS_URL   (default: http://192.168.1.73:5001)
  CANVAS_TOKEN (from .env file or environment)
"""

import json
import os
import sys
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

# ── Config ────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).parent.absolute()
ENV_FILE = PROJECT_DIR / ".env"

# Load .env manually (avoid pulling in python-dotenv as a hard dep)
CANVAS_URL = os.environ.get("CANVAS_URL", "http://192.168.1.73:5001")
CANVAS_TOKEN = os.environ.get("CANVAS_TOKEN", "")

if not CANVAS_TOKEN and ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("CANVAS_TOKEN="):
                CANVAS_TOKEN = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

# ── MCP Server ────────────────────────────────────────────────────────────
mcp = FastMCP(
    "Canvas",
    instructions="""
Push content to Canvas — a real-time agent display board.
Use the push_to_canvas tool to push markdown, code, diagrams, images, video, or HTML.
Cards appear instantly on the Canvas web UI (canvas.wodinga.studio).
"""
)

VALID_TYPES = {"markdown", "code", "mermaid", "svg", "html", "image", "video", "clear"}


@mcp.tool()
def push_to_canvas(
    board: str = "main",
    type: str = "markdown",
    content: str = "",
    title: str = "",
    agent: str = "casper",
    agent_emoji: str = "🐱",
    stream_only: bool = False,
) -> str:
    """Push content to a Canvas board. Content appears instantly in the browser UI.

    Args:
        board: Board name (e.g. 'main', 'research', 'blog', 'trading', 'infra')
        type: Content type — 'markdown', 'code', 'mermaid', 'svg', 'html', 'image', 'video', or 'clear'
        content: The content body. For 'clear' type, this can be empty.
        title: Optional card title
        agent: Agent name (for display on the card)
        agent_emoji: Agent emoji badge (for display on the card)
        stream_only: If True, don't persist to history (ephemeral)

    Returns:
        Status message with card ID and board name
    """
    global CANVAS_TOKEN, CANVAS_URL

    if type not in VALID_TYPES:
        return f"Error: invalid content type '{type}'. Valid types: {', '.join(sorted(VALID_TYPES))}"

    if not CANVAS_TOKEN:
        return "Error: CANVAS_TOKEN not found. Set it in .env or as an environment variable."

    payload = {
        "type": type,
        "content": content,
        "board": board,
        "title": title,
        "agent": agent,
        "agent_emoji": agent_emoji,
    }
    if stream_only:
        payload["stream_only"] = True

    try:
        resp = httpx.post(
            f"{CANVAS_URL}/push",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {CANVAS_TOKEN}",
            },
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        card_id = result.get("id", "?")
        return f"✅ Pushed to board '{board}' (type: {type}, id: {card_id})"
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        try:
            detail = e.response.json()
            return f"❌ HTTP {status}: {detail.get('error', e.response.text)}"
        except Exception:
            return f"❌ HTTP {status}: {e.response.text}"
    except httpx.ConnectError:
        return f"❌ Connection refused — is Canvas running at {CANVAS_URL}?"
    except Exception as e:
        return f"❌ Error: {e}"


def main():
    """Entry point with transport selection."""
    import argparse

    parser = argparse.ArgumentParser(description="Canvas MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio",
                        help="Transport protocol (default: stdio)")
    parser.add_argument("--port", type=int, default=8000,
                        help="Port for SSE transport (default: 8000)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host for SSE transport (default: 127.0.0.1)")
    args = parser.parse_args()

    if not CANVAS_TOKEN:
        print(f"⚠️  CANVAS_TOKEN not found in environment or {ENV_FILE}", file=sys.stderr)
        print("   Set CANVAS_TOKEN or ensure .env exists.", file=sys.stderr)

    print(f"🚀 Canvas MCP Server starting", file=sys.stderr)
    print(f"   Server: {mcp.name}", file=sys.stderr)
    print(f"   Canvas: {CANVAS_URL}", file=sys.stderr)
    print(f"   Transport: {args.transport}", file=sys.stderr)
    if args.transport == "sse":
        print(f"   Listening: http://{args.host}:{args.port}", file=sys.stderr)
        print(f"   SSE:       http://{args.host}:{args.port}/sse", file=sys.stderr)
        print(f"   Messages:  http://{args.host}:{args.port}/messages/", file=sys.stderr)
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        print("   Waiting for MCP client connection on stdin/stdout...", file=sys.stderr)
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()