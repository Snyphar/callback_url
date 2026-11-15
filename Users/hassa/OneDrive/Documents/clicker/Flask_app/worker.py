"""Telegram outbox worker.

Drains the `outbox` table in security.sqlite one message at a time and
delivers each to Telegram. Run this alongside the Flask app:

    python worker.py

The web app only ever *writes* to the outbox, so page requests never block
on the Telegram API. If Telegram is slow or down, the queue just grows and
the worker catches up when it can.

Design notes:
- Single claim at a time (ORDER BY id, status='pending', due now) preserves
  order, so messages arrive in the order they were generated.
- Failed sends retry with exponential backoff up to max_attempts, then the
  row is marked 'failed' with the last error and the worker moves on instead
  of getting stuck behind a poison message.
- Safe to run more than one worker: the claim is done in a BEGIN IMMEDIATE
  transaction, so a row is only worked by one process.
"""

import os
import sqlite3
import time
from pathlib import Path

import requests

# --- Telegram config -------------------------------------------------------
# Defaults match app.py; override with env vars for deployment.
TOKEN = os.environ.get("TELEGRAM_TOKEN", "9166168045:AAHG_zwrlfviXQtmbGuXuR44Bhn7EtYSIKU")
GROUP_ID = int(os.environ.get("TELEGRAM_GROUP_ID", "-5359001867"))
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

BASE_DIR = Path(__file__).resolve().parent
DATABASE = os.environ.get("DATABASE", str(BASE_DIR / "instance" / "security.sqlite"))

# --- Worker tuning ---------------------------------------------------------
POLL_INTERVAL = float(os.environ.get("WORKER_POLL_INTERVAL", "1.0"))  # idle sleep, seconds
BACKOFF_BASE = float(os.environ.get("WORKER_BACKOFF_BASE", "2.0"))    # seconds; doubled each attempt
REQUEST_TIMEOUT = 20


def connect():
    """Open one long-lived connection for the worker."""
    connection = sqlite3.connect(DATABASE, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS outbox ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "text TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'pending', "
        "attempts INTEGER NOT NULL DEFAULT 0, "
        "max_attempts INTEGER NOT NULL DEFAULT 5, "
        "last_error TEXT, "
        "next_attempt_at REAL NOT NULL DEFAULT 0, "
        "created_at REAL DEFAULT CURRENT_TIMESTAMP, "
        "sent_at REAL)"
    )
    return connection


def claim_next(connection):
    """Atomically claim the oldest due message, or return None."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            "SELECT * FROM outbox "
            "WHERE status = 'pending' AND next_attempt_at <= ? "
            "ORDER BY id LIMIT 1",
            (time.time(),),
        ).fetchone()
        if row is not None:
            connection.execute(
                "UPDATE outbox SET status = 'sending' WHERE id = ?", (row["id"],)
            )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return row


def send_to_telegram(text):
    response = requests.post(
        f"{BASE_URL}/sendMessage",
        json={"chat_id": GROUP_ID, "text": text},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram API error"))
    return data["result"]


def mark_sent(connection, row_id):
    connection.execute(
        "UPDATE outbox SET status = 'sent', sent_at = ?, last_error = NULL "
        "WHERE id = ?",
        (time.time(), row_id),
    )


def mark_retry_or_fail(connection, row, error):
    """Schedule a backoff retry, or give up if attempts are exhausted."""
    attempts = row["attempts"] + 1
    if attempts >= row["max_attempts"]:
        connection.execute(
            "UPDATE outbox SET status = 'failed', attempts = ?, last_error = ? "
            "WHERE id = ?",
            (attempts, str(error)[:500], row["id"]),
        )
        print(f"[worker] id={row['id']} FAILED after {attempts} attempts: {error}")
    else:
        delay = BACKOFF_BASE ** attempts
        connection.execute(
            "UPDATE outbox SET status = 'pending', attempts = ?, last_error = ?, "
            "next_attempt_at = ? WHERE id = ?",
            (attempts, str(error)[:500], time.time() + delay, row["id"]),
        )
        print(
            f"[worker] id={row['id']} attempt {attempts}/{row['max_attempts']} "
            f"failed ({error}); retrying in {delay:.0f}s"
        )


def recover_stuck(connection):
    """Requeue rows left in 'sending' by a previously crashed worker."""
    connection.execute(
        "UPDATE outbox SET status = 'pending' WHERE status = 'sending'"
    )


def run_once(connection):
    """Process a single message. Returns True if work was done."""
    row = claim_next(connection)
    if row is None:
        return False
    try:
        send_to_telegram(row["text"])
        mark_sent(connection, row["id"])
        print(f"[worker] id={row['id']} sent")
    except (requests.RequestException, RuntimeError, ValueError) as error:
        mark_retry_or_fail(connection, row, error)
    return True


def main():
    Path(DATABASE).parent.mkdir(exist_ok=True)
    connection = connect()
    recover_stuck(connection)
    print(f"[worker] watching outbox in {DATABASE}. Ctrl+C to stop.")

    while True:
        try:
            if not run_once(connection):
                time.sleep(POLL_INTERVAL)
        except sqlite3.Error as error:
            print(f"[worker] db error: {error}; reconnecting")
            time.sleep(2)
            try:
                connection.close()
            except sqlite3.Error:
                pass
            connection = connect()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[worker] stopped.")
