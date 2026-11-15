# Sending App

Flask app for uploading HTML templates, selecting a sending domain and prefix, and queuing emails through the email API.

## Setup

From the `sending_app` directory, create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `FLASK_SECRET` and `EMAIL_API_KEY`. Keep `.env` private. The SQLite database is created locally as `sending_app.db` and is ignored by Git.

## Create the admin account

Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and optionally `ADMIN_EMAIL` in `.env`, then run:

```powershell
python seed_admin.py
```

The script creates the account if it does not exist, or updates its password and admin status if it does. It never uses a built-in default password.

## Run locally

```powershell
python app.py
```

Open <http://127.0.0.1:5000> and sign in with the seeded admin account.

The queue worker runs inside the Flask process for local use. For production, run the worker separately or replace it with a real task queue, and use a production database instead of SQLite.
