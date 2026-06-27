"""
Canvas — Real-time content push display board.
Casper pushes, Raf views. SSE-based, multi-board.
"""

import json
import queue
import time
import uuid
from collections import defaultdict
from flask import Flask, render_template, request, Response, jsonify

app = Flask(__name__)

# ── Live-editing: template changes take effect immediately, no restart ──
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# In-memory storage: board_id -> list of {id, type, content, timestamp}
BOARDS = defaultdict(list)
# SSE subscribers: board_id -> set of Queue objects
SUBSCRIBERS = defaultdict(set)
MAX_HISTORY = 200


def get_board(name):
    return BOARDS[name]


def add_to_board(board_id, item):
    board = get_board(board_id)
    board.append(item)
    if len(board) > MAX_HISTORY:
        board[:] = board[-MAX_HISTORY:]
    # Notify all subscribers
    dead = set()
    for q in SUBSCRIBERS[board_id]:
        try:
            q.put_nowait(item)
        except queue.Full:
            dead.add(q)
    SUBSCRIBERS[board_id] -= dead


def clear_board(board_id):
    BOARDS[board_id] = []
    # Notify subscribers of clear
    item = {"id": "clear", "type": "clear", "content": "", "timestamp": time.time()}
    dead = set()
    for q in SUBSCRIBERS[board_id]:
        try:
            q.put_nowait(item)
        except queue.Full:
            dead.add(q)
    SUBSCRIBERS[board_id] -= dead


def board_exists(name):
    return name in BOARDS


# ─── Routes ────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    board_id = request.args.get("board", "main")
    return render_template("index.html", board_id=board_id)


@app.route("/push", methods=["POST"])
def push():
    data = request.get_json(force=True)
    board_id = data.get("board", "main")
    content_type = data.get("type", "markdown")
    content = data.get("content", "")
    stream_only = data.get("stream_only", False)
    agent = data.get("agent", "unknown")
    agent_emoji = data.get("agent_emoji", "🤖")

    item = {
        "id": str(uuid.uuid4()),
        "type": content_type,
        "content": content,
        "title": data.get("title", ""),
        "agent": agent,
        "agent_emoji": agent_emoji,
        "timestamp": time.time(),
    }

    if content_type == "clear":
        clear_board(board_id)
        return jsonify({"status": "ok", "board": board_id, "action": "cleared"})

    if not stream_only:
        add_to_board(board_id, item)
    else:
        # stream_only: send to SSE clients but don't store in history
        dead = set()
        for q in SUBSCRIBERS[board_id]:
            try:
                q.put_nowait(item)
            except queue.Full:
                dead.add(q)
        SUBSCRIBERS[board_id] -= dead

    return jsonify({"status": "ok", "id": item["id"], "board": board_id})


@app.route("/history/<board_id>")
def history(board_id):
    """Return recent history for a board as JSON."""
    board = get_board(board_id)
    # Return in reverse chronological so newest first, but client can handle
    return jsonify(list(board))


@app.route("/stream/<board_id>")
def stream(board_id):
    """SSE endpoint for real-time push."""
    q = queue.Queue(maxsize=100)

    def event_stream():
        SUBSCRIBERS[board_id].add(q)
        try:
            # Send initial keepalive
            yield "data: \n\n"
            while True:
                item = q.get()
                data = json.dumps(item)
                yield f"data: {data}\n\n"
        except GeneratorExit:
            pass
        finally:
            SUBSCRIBERS[board_id].discard(q)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/boards")
def list_boards():
    """List all boards that have content."""
    return jsonify(sorted(BOARDS.keys()))


@app.route("/health")
def health():
    """Health check — confirms canvas is alive."""
    return jsonify({"status": "ok", "boards": len(BOARDS), "uptime": "alive"})


@app.route("/reload", methods=["POST"])
def reload_templates():
    """Reload templates without restart — use after editing index.html."""
    app.jinja_env.cache.clear()
    return jsonify({"status": "ok", "message": "Templates reloaded"})


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
