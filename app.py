"""
Canvas — Real-time content push display board.
Casper pushes, Raf views. SSE-based, multi-board.
"""

import json
import os
import queue
import sqlite3
import time
import uuid
from collections import defaultdict
from flask import Flask, render_template, request, Response, jsonify, make_response

app = Flask(__name__)

# ── Live-editing: template changes take effect immediately, no restart ──
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# ── SQLite database ────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "canvas.db")


def get_db():
    """Open a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the database and cards table if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id TEXT PRIMARY KEY,
            board TEXT NOT NULL,
            type TEXT NOT NULL,
            content TEXT,
            title TEXT,
            agent TEXT,
            agent_emoji TEXT,
            timestamp REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_board ON cards(board)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_timestamp ON cards(timestamp)")
    conn.commit()
    conn.close()


def load_all_cards():
    """Load all cards from SQLite into in-memory BOARDS, sorted by timestamp."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM cards ORDER BY board, timestamp ASC"
    ).fetchall()
    conn.close()

    boards = defaultdict(list)
    for row in rows:
        item = {
            "id": row["id"],
            "type": row["type"],
            "content": row["content"],
            "title": row["title"] or "",
            "agent": row["agent"] or "",
            "agent_emoji": row["agent_emoji"] or "",
            "timestamp": row["timestamp"],
        }
        boards[row["board"]].append(item)

    return boards


def save_card_to_db(board_id, item):
    """Persist a single card to the SQLite database."""
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO cards (id, board, type, content, title, agent, agent_emoji, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item["id"],
            board_id,
            item["type"],
            json.dumps(item["content"]) if not isinstance(item["content"], str) else item["content"],
            item.get("title", ""),
            item.get("agent", ""),
            item.get("agent_emoji", ""),
            item["timestamp"],
        ),
    )
    conn.commit()
    conn.close()


def clear_board_in_db(board_id):
    """Remove all cards for a given board from SQLite."""
    conn = get_db()
    conn.execute("DELETE FROM cards WHERE board = ?", (board_id,))
    conn.commit()
    conn.close()


# ── In-memory storage ──────────────────────────────────────────────────────

# In-memory storage: board_id -> list of {id, type, content, timestamp}
BOARDS = defaultdict(list)
# SSE subscribers: board_id -> set of Queue objects
SUBSCRIBERS = defaultdict(set)


def get_board(name):
    return BOARDS[name]


def add_to_board(board_id, item):
    board = get_board(board_id)
    board.append(item)
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
    response = make_response(render_template("index.html", board_id=board_id))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/test")
def test():
    """Zero-dependency test page — proves the pipeline works without CDNs."""
    board_id = request.args.get("board", "main")
    return render_template("minimal.html", board_id=board_id)


@app.route("/push", methods=["POST"])
def push():
    data = request.get_json(force=True)
    board_id = data.get("board", "main")
    content_type = data.get("type", "markdown")
    content = data.get("content", "")
    stream_only = data.get("stream_only", False)
    agent = data.get("agent", "unknown")
    agent_emoji = data.get("agent_emoji", "🤖")
    card_id = data.get("card_id")

    # ── Clear board ────────────────────────────────────────────────────
    if content_type == "clear":
        clear_board(board_id)
        clear_board_in_db(board_id)
        return jsonify({"status": "ok", "board": board_id, "action": "cleared"})

    # ── Build item: update or create ───────────────────────────────────
    is_update = False
    if card_id:
        board = get_board(board_id)
        existing = next((c for c in board if c["id"] == card_id), None)
        if existing:
            # Update in-place — preserve id and timestamp
            existing["type"] = content_type
            existing["content"] = content
            existing["title"] = data.get("title", "")
            existing["agent"] = agent
            existing["agent_emoji"] = agent_emoji
            item = existing
            is_update = True
        else:
            # Card id provided but not found — create new with that id
            item = {
                "id": card_id,
                "type": content_type,
                "content": content,
                "title": data.get("title", ""),
                "agent": agent,
                "agent_emoji": agent_emoji,
                "timestamp": time.time(),
            }
            board.append(item)
    else:
        # Regular create with new UUID
        item = {
            "id": str(uuid.uuid4()),
            "type": content_type,
            "content": content,
            "title": data.get("title", ""),
            "agent": agent,
            "agent_emoji": agent_emoji,
            "timestamp": time.time(),
        }

    # ── Add action field for SSE consumers ─────────────────────────────
    item["action"] = "update" if is_update else "create"

    # ── Persist and notify ─────────────────────────────────────────────
    if stream_only:
        # Send to SSE clients only, don't store in history
        dead = set()
        for q in SUBSCRIBERS[board_id]:
            try:
                q.put_nowait(item)
            except queue.Full:
                dead.add(q)
        SUBSCRIBERS[board_id] -= dead
    else:
        if is_update:
            # Card already in BOARDS (updated in-place above) — just persist
            save_card_to_db(board_id, item)
        else:
            # New card — add to in-memory list and persist
            add_to_board(board_id, item)
            # add_to_board already notifies SSE, skip duplicate notification below
            save_card_to_db(board_id, item)

        if is_update:
            # Notify SSE subscribers for the update
            dead = set()
            for q in SUBSCRIBERS[board_id]:
                try:
                    q.put_nowait(item)
                except queue.Full:
                    dead.add(q)
            SUBSCRIBERS[board_id] -= dead

    return jsonify({
        "status": "ok",
        "id": item["id"],
        "board": board_id,
        "action": item["action"],
    })


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
    # Initialize SQLite and load history into memory
    init_db()
    loaded = load_all_cards()
    for board_id, items in loaded.items():
        BOARDS[board_id] = items
    print(f"Loaded {sum(len(v) for v in BOARDS.values())} cards from SQLite across {len(BOARDS)} board(s)")

    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, threaded=True)
