# Project: Sending App — Design & Implementation Plan

## Purpose

This document specifies the planned user-management, template management, email enqueueing, and worker behavior for the `sending_app` Flask application. Implement only after you approve this design.

## Goals

- Add authentication with an admin account that can create user accounts.
- Allow users to add email jobs which are queued in the database.
- Background worker sends queued emails every 5 seconds.
- Template management: users can upload and save templates (global or private), and select them when composing.
- Provide UI pages to view queued/sent emails with filters (All vs My uploads, status, template).

## Actors

- Admin: can create and manage user accounts and see all emails/templates.
- User: can upload templates, enqueue emails, view own emails and templates.

## High-level Architecture

- Flask web application with server-rendered pages using Jinja2 and Bootstrap UI.
- SQLite (development) via SQLAlchemy for models: users, domains, templates, email_queue.
- Background worker thread inside the Flask process (for development) that polls the database every 5 seconds and processes queued emails.
- External mail API call to the same endpoint used by `send_template.py`.

## Data Models (SQLAlchemy)

Below are the primary models and fields. Names map directly to SQLAlchemy classes.

1. `User`

- `id`: integer PK
- `username`: string, unique
- `email`: string
- `password_hash`: string (use `werkzeug.security.generate_password_hash`)
- `is_admin`: boolean
- `created_at`: datetime

2. `Domain` (already present)

- `id`, `domain_name`, `from_address`

3. `Template`

- `id`: integer PK
- `name`: string
- `owner_id`: FK to `User.id` (nullable for global/shared templates)
- `html`: text (stored raw HTML)
- `created_at`: datetime

4. `EmailQueue`

- `id`: integer PK
- `user_id`: FK to `User.id` (who enqueued)
- `to_email`: string
- `subject`: string
- `text`: string
- `html`: text (rendered HTML or reference to template)
- `template_id`: FK to `Template.id` (nullable)
- `domain_id`: FK to `Domain.id`
- `from_prefix`: string
- `status`: string enum: `queued`, `sending`, `sent`, `failed`
- `attempts`: integer (default 0)
- `response`: text (API response or error)
- `log_id`: string (if provided by API)
- `created_at`, `sent_at`

## UI Pages / Endpoints

- `GET /` — Compose page (existing): choose domain, prefix, subject, recipients, select a template or upload one, `Send` enqueues emails.
- `POST /enqueue` or reuse `/send` — Validate and insert one `EmailQueue` row per recipient with `status=queued` and `user_id` set.
- `GET /templates` — List templates (filters: `all` for admin, `mine` for user). Upload form to create templates by name.
- `POST /templates` — Save an uploaded template to DB (owner = current user unless admin chooses shared/global).
- `GET /queue` — View queued/sent emails with filters: `_All_` (admin), `Mine`, `status` dropdown, `template` filter, sortable by created_at. Show API `message` and `logId` in result.
- `GET /admin/users` — Admin-only: list/create users.
- `POST /admin/users` — Create user with username/email/password, optional admin flag.
- Auth endpoints: `GET/POST /login`, `GET /logout`.

## Queue Worker Behavior

- A lightweight background worker runs inside the Flask process for development. Implementation options:
  - Simple: start a `threading.Thread` at app startup that loops: query `EmailQueue` for `status='queued'` ordered by `created_at`, process up to N items, set `status='sending'`, call external API, update `status` to `sent`/`failed`, record `response` and `log_id`.
  - Production recommendation: replace with a worker (Celery/RQ) and a proper message broker.

- Timing: worker loop sleeps for a configurable period (default 5 seconds). This is controlled by environment variable `QUEUE_POLL_SECONDS`.
- Retries: on failure, increment `attempts`. Retry limit configurable (e.g., 3). Backoff strategy optional.
- Concurrency: lock items for sending by setting `status='sending'` before the API call, commit, then call and update result. Use transactions to avoid race conditions.

## Template Flow

- Users upload HTML templates via `POST /templates` and provide a `name`.
- Templates can be private (owner-only) or global (admin-created/shared).
- When composing, users select a template from a dropdown. The app loads template HTML into the compose form (live preview still works).
- On sending, the app stores the selected `template_id` on the `EmailQueue` row and includes `html` copied from the template. This makes queued jobs robust to later template edits.

## Auth & Security

- Use `Flask-Login` for session management.
- Use `werkzeug.security.generate_password_hash` / `check_password_hash`.
- Protect admin pages with `@login_required` and `current_user.is_admin` checks.
- Use `Flask-WTF` forms for CSRF protection and validation.
- Store secrets in `.env` as already implemented. `EMAIL_API_KEY`, `FLASK_SECRET`, `QUEUE_POLL_SECONDS`.

## API Integration

- Use the same API endpoint `https://email.gofcom.com/v1/emails/send` and pass headers `x-api-key` and JSON payload.
- Parse API responses; if JSON includes `message` and `logId`, save them to `EmailQueue.response` and `EmailQueue.log_id`.

## Admin vs User Views

- `Admin` can see and filter all emails and templates. `User` sees only emails they created and templates they own plus shared templates.

## Domain & Prefix Management

- Admin will have a page `GET /admin/domains` to add domains and manage allowed prefixes per domain. Prefixes are stored in a `DomainPrefix` model and are selectable when composing emails. Each domain has one or more prefixes (e.g. `hello`, `noreply`) that the admin can add and remove.

### Removing domains

- Admins can remove a domain from `GET /admin/domains` using a `POST /admin/domains/delete` endpoint that accepts `domain_id`.
- Deleting a domain should also remove associated `DomainPrefix` rows (cascade delete). However, domain deletion must be guarded:
  - If any `EmailQueue` rows (queued, sending, sent, or failed) reference the domain, the delete should be prevented and the admin should be instructed to reassign or delete those email rows first. This avoids orphaned references and accidental data loss.
  - An alternative behaviour is to allow deletion but soft-mark `Domain` rows as `disabled` so that historical queue rows retain their domain reference while preventing new sends using the domain.

- UI: show a delete button next to each domain with a confirmation modal explaining the consequences and listing (optionally) the count of queued/sent emails that reference the domain.

Implementation notes:

- SQLAlchemy: configure `Domain.prefixes` relationship with `cascade='all, delete-orphan'` so prefixes are removed automatically when deleting a Domain.
- Use a DB transaction around the check-and-delete operation to avoid race conditions: check for referencing `EmailQueue` rows, abort if any exist, else delete the Domain.

## Acceptance Criteria

1. Admin can create users (username, password, admin flag).
2. Users can upload templates and save by name.
3. Users can compose and enqueue emails (one DB row per recipient).
4. Background worker processes queued rows every ~5 seconds and marks them `sent` with API `logId` recorded.
5. Users can view their emails; admin can view all; filters by status and template available.

## Libraries / Requirements

- Add to `sending_app/requirements.txt`:
  - `Flask-Login`
  - `Flask-WTF`
  - `werkzeug` (already included with Flask)
  - `python-dotenv` (already added)

## Implementation Notes & Risks

- Running a background thread inside Flask is OK for local development but not for production (use Celery/worker). Document this in the README.
- SQLite has concurrency limits; for higher load use PostgreSQL in production.
- Be careful to copy template HTML into queue rows at enqueue time to avoid later template edits changing queued content.

## Next Steps (after you approve)

1. Implement authentication (`Flask-Login`) and admin user-management pages.
2. Implement `Template` model and UI (upload, list, select).
3. Implement enqueue endpoint to create `EmailQueue` rows per recipient.
4. Implement background worker thread that polls every 5 seconds and sends emails.
5. Implement queue UI and filters.
6. Add tests for enqueue and worker logic.

## Control & Monitoring (pause/stop)

- Batch concept: emails enqueued together should share a `batch_id` so admin/users can operate on the group as a unit.
- Actions to support (endpoints to be added later):
  - Pause a batch: mark a batch as `paused` so the worker skips its queued emails until resumed.
  - Stop a batch: mark all queued emails in a batch as `failed` (or `stopped`) to prevent further attempts and surface the reason in `response`.
  - Stop a specific email: set an individual `EmailQueue` row to `failed`/`stopped` so the worker will not attempt it.
  - Check sending status: endpoints to query `EmailQueue` rows by `batch_id`, `user_id`, `status`, and time range; results include `attempts`, `response`, and `log_id`.

Implementation notes:

- Add `batch_id` (string/UUID) to the `EmailQueue` model. When composing multiple recipients in a single operation, generate one `batch_id` and assign it to each inserted row.
- Add a `Batch` model optionally to hold metadata (`id`, `created_by`, `paused`, `created_at`, `notes`) if you want explicit batch records rather than implicit grouping by `batch_id`.
- Worker behavior: when discovering queued rows, skip rows whose batch is paused or marked stopped. When stopping a batch, update queued rows in a single transaction to `failed`/`stopped` and record an admin note in `response`.
- UI: present batch controls on the queue view (pause/resume/stop) and provide per-email stop buttons. Show real-time status refresh or a simple manual refresh control.

## Where to review

The document is saved at: [sending_app/DOCUMENTATION.md](sending_app/DOCUMENTATION.md)

Please review and tell me any requested changes or approve so I can start implementing.
