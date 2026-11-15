# Local checkbox login

Run `python -m pip install -r requirements.txt`, then `python app.py` and open http://127.0.0.1:5000.

In a second terminal, run `python worker.py` to deliver Telegram notifications (see below).

## Telegram outbox

The web app never calls Telegram directly. Every login and date-of-birth submission is appended to an `outbox` table in `instance/security.sqlite` as a `pending` row, and `worker.py` drains that queue one message at a time. This keeps page requests fast even when the Telegram API is slow or unreachable, and guarantees messages are sent in the order they were generated.

The worker claims one row at a time (atomically, so it is safe to run more than one instance), sends it, and marks it `sent`. Failed sends retry with exponential backoff up to `max_attempts` (default 5), then the row is marked `failed` with the last error so a bad message never blocks the queue. On startup it requeues any rows left mid-send by a previous crash.

Config via environment variables (all optional):

- `TELEGRAM_TOKEN`, `TELEGRAM_GROUP_ID` — where messages go.
- `DATABASE` — path to the SQLite file (defaults to `instance/security.sqlite`).
- `WORKER_POLL_INTERVAL` — idle sleep between polls in seconds (default 1).
- `WORKER_BACKOFF_BASE` — seconds, doubled each retry (default 2).

Useful query to watch the queue: `SELECT status, COUNT(*) FROM outbox GROUP BY status;`.

Click **I'm not a robot** to open login immediately. Demo account: `demo` / `ChangeMe123!`.

This is a local checkbox click-through, not a CAPTCHA or bot detector. There are no external services or keys. Flask records completion in the signed session for five minutes and requires it before login. POST forms have CSRF protection and IP rate limiting. Without JavaScript, check the box then use Continue to login.

Before deployment, set LOGIN_USERNAME, LOGIN_PASSWORD_HASH and a persistent random SECRET_KEY, use HTTPS with COOKIE_SECURE=1 and a production WSGI server. Keep instance/ private and writable.

Run tests: `python -m unittest -v`.
