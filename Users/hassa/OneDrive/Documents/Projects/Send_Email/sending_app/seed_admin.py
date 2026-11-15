"""Create or update the administrator account from environment variables."""

import os
import sys

from werkzeug.security import generate_password_hash

from app import User, app, db, init_db


ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip() or None


if not ADMIN_USERNAME or not ADMIN_PASSWORD:
    print("Set ADMIN_USERNAME and ADMIN_PASSWORD before running this script.")
    sys.exit(1)

if len(ADMIN_PASSWORD) < 8:
    print("ADMIN_PASSWORD must be at least 8 characters long.")
    sys.exit(1)

with app.app_context():
    init_db()
    user = User.query.filter_by(username=ADMIN_USERNAME).first()

    if user is None:
        user = User(username=ADMIN_USERNAME)
        db.session.add(user)

    user.email = ADMIN_EMAIL
    user.password_hash = generate_password_hash(ADMIN_PASSWORD)
    user.is_admin = True
    user.is_active = True
    db.session.commit()

    print(f"Admin account ready: {user.username}")
