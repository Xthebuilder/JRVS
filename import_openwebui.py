#!/usr/bin/env python3
"""
Import Open WebUI chat history into JARVIS conversations table.

Reads directly from the Open WebUI Docker container's SQLite database and
inserts flattened message pairs into JARVIS's local jarvis.db.

Usage:
    python import_openwebui.py [--dry-run]

Options:
    --dry-run   Preview what would be imported without writing anything.
"""

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

JARVIS_DB = Path(__file__).parent / "data" / "jarvis.db"
OPENWEBUI_DB_PATH = "/app/backend/data/webui.db"
CONTAINER_NAME = "open-webui"
SOURCE_TAG = "openwebui"


def copy_db_from_container() -> Path:
    """Copy Open WebUI's SQLite file out of the Docker container."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    result = subprocess.run(
        ["docker", "cp", f"{CONTAINER_NAME}:{OPENWEBUI_DB_PATH}", tmp.name],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: Could not copy DB from container '{CONTAINER_NAME}'.")
        print(result.stderr)
        sys.exit(1)
    return Path(tmp.name)


def clean_content(text: str) -> str:
    """Strip Open WebUI's <details type='reasoning'> thinking blocks."""
    text = re.sub(r"<details[^>]*>.*?</details>", "", text, flags=re.DOTALL)
    return text.strip()


def load_openwebui_chats(db_path: Path) -> list[dict]:
    """Return all chats as a list of dicts with flattened message pairs."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, title, created_at, updated_at, chat FROM chat ORDER BY created_at"
    ).fetchall()
    conn.close()

    chats = []
    for chat_id, title, created_at, updated_at, chat_json in rows:
        if not chat_json:
            continue
        data = json.loads(chat_json)
        messages = data.get("messages", [])
        models = data.get("models", [])
        model = models[0] if models else "unknown"

        # Pair up user → assistant turns in order
        pairs = []
        pending_user = None
        for msg in messages:
            role = msg.get("role", "")
            content = clean_content(msg.get("content") or "")
            ts = msg.get("timestamp", created_at)

            if role == "user":
                pending_user = (content, ts)
            elif role == "assistant" and pending_user:
                pairs.append({
                    "session_id": chat_id,
                    "user_message": pending_user[0],
                    "ai_response": content,
                    "model_used": model,
                    "context_used": json.dumps({"source": SOURCE_TAG, "chat_title": title}),
                    "created_at": datetime.fromtimestamp(
                        ts if isinstance(ts, (int, float)) else created_at,
                        tz=timezone.utc,
                    ).strftime("%Y-%m-%d %H:%M:%S"),
                })
                pending_user = None

        if pairs:
            chats.append({"title": title, "pairs": pairs})

    return chats


def get_existing_session_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT session_id FROM conversations WHERE context_used LIKE ?",
        (f'%"{SOURCE_TAG}"%',),
    ).fetchall()
    return {r[0] for r in rows}


def import_chats(chats: list[dict], dry_run: bool) -> None:
    conn = sqlite3.connect(JARVIS_DB)
    existing = get_existing_session_ids(conn)

    total_new = 0
    total_skipped = 0

    for chat in chats:
        session_id = chat["pairs"][0]["session_id"]
        if session_id in existing:
            total_skipped += len(chat["pairs"])
            continue

        print(f"  {'[DRY RUN] ' if dry_run else ''}Importing: {chat['title']!r}  "
              f"({len(chat['pairs'])} turns)")

        if not dry_run:
            conn.executemany(
                """INSERT INTO conversations
                       (session_id, user_message, ai_response, model_used,
                        context_used, created_at, embedded)
                   VALUES (:session_id, :user_message, :ai_response, :model_used,
                           :context_used, :created_at, 0)""",
                chat["pairs"],
            )
        total_new += len(chat["pairs"])

    if not dry_run:
        conn.commit()
    conn.close()

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Imported : {total_new} conversation turns")
    print(f"  Skipped  : {total_skipped} turns (already in DB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to JARVIS DB")
    args = parser.parse_args()

    print(f"Copying Open WebUI database from container '{CONTAINER_NAME}'...")
    tmp_db = copy_db_from_container()

    try:
        print("Parsing chats...")
        chats = load_openwebui_chats(tmp_db)
        print(f"Found {len(chats)} chats with at least one message pair.\n")

        import_chats(chats, dry_run=args.dry_run)
    finally:
        tmp_db.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
