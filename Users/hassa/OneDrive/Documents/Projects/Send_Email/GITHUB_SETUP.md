# Add Sending App to an Existing Repository

This guide assumes the destination GitHub repository already exists and has been cloned locally.

## 1. Clone the existing repository

Skip this step if the repository is already on your computer.

```powershell
git clone https://github.com/<owner>/<repository>.git
cd <repository>
```

Do not run `git init` when adding this project to an existing repository.

## 2. Copy the project files

Copy the project into the repository while preserving this structure:

```text
<repository>/
  .env.example
  .gitignore
  send_template.py
  template.html
  sending_app/
    app.py
    seed_admin.py
    requirements.txt
    templates/
    static/
```

If the repository already has a `.gitignore`, merge the rules from this project into it instead of replacing existing rules.

## 3. Check the files before staging

From the repository root, confirm the application files are present:

```powershell
Get-ChildItem .\sending_app
```

Review the changes:

```powershell
git status
```

## 4. Create local configuration

Copy the example file to a real `.env` file:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set:

```text
FLASK_SECRET=<long-random-secret>
EMAIL_API_KEY=<email-api-key>
ADMIN_USERNAME=<admin-username>
ADMIN_PASSWORD=<strong-admin-password>
ADMIN_EMAIL=<admin-email>
```

Never commit `.env`, API keys, passwords, or `sending_app.db`. The included `.gitignore` excludes them.

## 5. Install the application

```powershell
cd sending_app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 6. Create the administrator

Run this from the `sending_app` directory after setting the admin values in `.env`:

```powershell
python seed_admin.py
```

The command creates the admin account or updates the matching username. It does not use a default password.

## 7. Start and verify the app

```powershell
python app.py
```

Open <http://127.0.0.1:5000>, sign in, and verify the dashboard and admin pages. Stop the server with `Ctrl+C` when finished.

## 8. Stage and push only safe files

Return to the repository root and inspect the staged file list:

```powershell
cd ..
git status --short
git add .
git status --short
```

The staged list should not contain `.env`, `.venv`, `sending_app.db`, or Python cache files. Commit and push after reviewing it:

```powershell
git commit -m "Add sending application"
git push origin main
```

Use the repository's actual branch name if it is not `main`.

## 9. Set up another machine

After cloning the repository elsewhere, repeat steps 4 through 7. Each machine should have its own `.env`, virtual environment, database, and admin credentials.

## Production note

The built-in queue worker runs inside the Flask process and SQLite is intended for local or small deployments. For production, use a production WSGI server, a separate background worker, and a database such as PostgreSQL.
