from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
import os
import requests
from pathlib import Path
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import threading
import time
import uuid

# Load project-level settings, while keeping the local app .env supported.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / '.env')
load_dotenv(dotenv_path=Path(__file__).with_name('.env'), override=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET') or os.urandom(32)
db_path = Path(__file__).with_name('sending_app.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


class Domain(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    domain_name = db.Column(db.String(255), unique=True, nullable=False)
    from_address = db.Column(db.String(255), nullable=False)


class DomainPrefix(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domain.id'), nullable=False)
    prefix = db.Column(db.String(128), nullable=False)
    domain = db.relationship('Domain', backref=db.backref('prefixes', cascade='all, delete-orphan'))


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class Template(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    html = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    owner = db.relationship('User', backref=db.backref('templates', lazy='dynamic'))


class EmailQueue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(64), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    to_email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=True)
    text = db.Column(db.Text, nullable=True)
    html = db.Column(db.Text, nullable=True)
    template_id = db.Column(db.Integer, db.ForeignKey('template.id'), nullable=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domain.id'), nullable=True)
    from_prefix = db.Column(db.String(128), nullable=True)
    status = db.Column(db.String(32), default='queued', index=True)
    attempts = db.Column(db.Integer, default=0)
    response = db.Column(db.Text, nullable=True)
    log_id = db.Column(db.String(128), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    sent_at = db.Column(db.DateTime, nullable=True)
    user = db.relationship('User', backref=db.backref('emails', lazy='dynamic'))
    template = db.relationship('Template')
    domain = db.relationship('Domain')


class Batch(db.Model):
    id = db.Column(db.String(64), primary_key=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    paused = db.Column(db.Boolean, default=False)
    stopped = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    notes = db.Column(db.Text, nullable=True)
    creator = db.relationship('User')


def init_db():
    db.create_all()
    # Add fields introduced after the initial SQLite database was created.
    user_columns = {column['name'] for column in db.session.execute(db.text('PRAGMA table_info(user)')).mappings()}
    if 'is_active' not in user_columns:
        db.session.execute(db.text('ALTER TABLE user ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1'))
        db.session.commit()
    if Domain.query.count() == 0:
        domains = [
            Domain(domain_name='smsbusinesshelp.com', from_address='hello@smsbusinesshelp.com'),
            Domain(domain_name='example.com', from_address='noreply@example.com'),
        ]
        db.session.add_all(domains)
        db.session.commit()
    # ensure prefixes table exists and seed a default prefix for sample domain
    if DomainPrefix.query.count() == 0:
        d = Domain.query.filter_by(domain_name='smsbusinesshelp.com').first()
        if d:
            db.session.add(DomainPrefix(domain_id=d.id, prefix='hello'))
            db.session.commit()
with app.app_context():
    init_db()


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.is_active and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('Logged in', 'info')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out', 'info')
    return redirect(url_for('login'))


def send_single_email(eq: EmailQueue, api_key: str):
    url = "https://email.gofcom.com/v1/emails/send"
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "from": eq.domain.from_address if eq.domain else None,
        "to": eq.to_email,
        "subject": eq.subject or '',
        "domainName": eq.domain.domain_name if eq.domain else None,
        "fromPrefix": eq.from_prefix or '',
        "text": eq.text or '',
        "html": eq.html or '',
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        eq.response = str(body)
        if isinstance(body, dict):
            eq.log_id = body.get('logId') or body.get('log_id')
        eq.status = 'sent' if resp.status_code >= 200 and resp.status_code < 300 else 'failed'
        eq.attempts = eq.attempts + 1
        if eq.status == 'sent':
            eq.sent_at = db.func.now()
    except Exception as e:
        eq.attempts = eq.attempts + 1
        eq.status = 'failed'
        eq.response = str(e)
    finally:
        db.session.commit()


def worker_loop():
    print("Starting email sending worker thread at 5-second intervals...")
    poll = int(os.environ.get('QUEUE_POLL_SECONDS', '5'))
    api_key = os.environ.get('EMAIL_API_KEY')
    while True:
        try:
            if not api_key:
                time.sleep(poll)
                continue
            # fetch a few queued emails
            with app.app_context():
                q = EmailQueue.query.filter_by(status='queued').order_by(EmailQueue.created_at.asc()).limit(10).all()
                for eq in q:
                    # skip if batch is paused or stopped
                    if eq.batch_id:
                        b = db.session.get(Batch, eq.batch_id)
                        if b and (b.paused or b.stopped):
                            continue
                    # mark sending to avoid duplicates
                    eq.status = 'sending'
                    db.session.commit()
                    send_single_email(eq, api_key)
        except Exception:
            pass
        time.sleep(poll)


def start_worker():
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()

# start worker
start_worker()


@app.route('/', methods=['GET'])
@login_required
def root():
    return redirect(url_for('dashboard'))


@app.route('/compose', methods=['GET'])
@login_required
def compose():
    domains = Domain.query.order_by(Domain.domain_name).all()
    templates = Template.query.filter((Template.owner_id == None) | (Template.owner_id == current_user.id)).order_by(Template.created_at.desc()).all()
    return render_template('index.html', domains=domains, templates=templates)


@app.route('/dashboard', methods=['GET'])
@login_required
def index():
    email_query = EmailQueue.query
    batch_query = Batch.query
    if not current_user.is_admin:
        email_query = email_query.filter_by(user_id=current_user.id)
        batch_query = batch_query.filter_by(created_by=current_user.id)

    status_counts = {
        status: email_query.filter_by(status=status).count()
        for status in ('sent', 'queued', 'sending', 'failed')
    }
    total_emails = sum(status_counts.values())
    delivery_rate = round(status_counts['sent'] / total_emails * 100, 1) if total_emails else 0

    recent_batches = batch_query.order_by(Batch.created_at.desc()).limit(5).all()
    batch_summaries = []
    for batch in recent_batches:
        batch_summaries.append({
            'batch': batch,
            'count': EmailQueue.query.filter_by(batch_id=batch.id).count(),
            'sent': EmailQueue.query.filter_by(batch_id=batch.id, status='sent').count(),
            'failed': EmailQueue.query.filter_by(batch_id=batch.id, status='failed').count(),
        })

    recent_emails = email_query.order_by(EmailQueue.created_at.desc()).limit(8).all()
    templates_query = Template.query.filter((Template.owner_id == None) | (Template.owner_id == current_user.id))

    return render_template(
        'dashboard.html',
        status_counts=status_counts,
        total_emails=total_emails,
        delivery_rate=delivery_rate,
        total_batches=batch_query.count(),
        total_templates=templates_query.count(),
        total_domains=Domain.query.count(),
        total_users=User.query.count() if current_user.is_admin else None,
        batch_summaries=batch_summaries,
        recent_emails=recent_emails,
    )


@app.route('/admin/domains', methods=['GET'])
@login_required
def admin_domains():
    if not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('index'))
    domains = Domain.query.order_by(Domain.domain_name).all()
    return render_template('admin_domains.html', domains=domains)


@app.route('/admin/users', methods=['GET'])
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('index'))
    users = User.query.order_by(User.username).all()
    return render_template('admin_users.html', users=users)


@app.route('/admin/users/create', methods=['POST'])
@login_required
def create_user():
    if not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('index'))
    username = request.form.get('username')
    password = request.form.get('password')
    is_admin = bool(request.form.get('is_admin'))
    if not username or not password:
        flash('username and password required', 'danger')
        return redirect(url_for('admin_users'))
    if User.query.filter_by(username=username).first():
        flash('username already exists', 'danger')
        return redirect(url_for('admin_users'))
    u = User(username=username, password_hash=generate_password_hash(password), is_admin=is_admin)
    db.session.add(u)
    db.session.commit()
    flash('User created', 'info')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/update-password', methods=['POST'])
@login_required
def update_user_password():
    if not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('index'))
    user = db.session.get(User, request.form.get('user_id'))
    password = request.form.get('password', '')
    if not user or not password:
        flash('User and password are required', 'danger')
        return redirect(url_for('admin_users'))
    user.password_hash = generate_password_hash(password)
    db.session.commit()
    flash('Password updated', 'info')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/toggle-active', methods=['POST'])
@login_required
def toggle_user_active():
    if not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('index'))
    user = db.session.get(User, request.form.get('user_id'))
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('admin_users'))
    if user.id == current_user.id:
        flash('You cannot change your own active status', 'danger')
        return redirect(url_for('admin_users'))
    user.is_active = not user.is_active
    db.session.commit()
    flash('User status updated', 'info')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/delete', methods=['POST'])
@login_required
def delete_user():
    if not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('index'))
    user = db.session.get(User, request.form.get('user_id'))
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('admin_users'))
    if user.id == current_user.id:
        flash('You cannot delete your own account', 'danger')
        return redirect(url_for('admin_users'))
    EmailQueue.query.filter_by(user_id=user.id).update({'user_id': None}, synchronize_session=False)
    Batch.query.filter_by(created_by=user.id).update({'created_by': None}, synchronize_session=False)
    Template.query.filter_by(owner_id=user.id).update({'owner_id': None}, synchronize_session=False)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted', 'info')
    return redirect(url_for('admin_users'))


@app.route('/admin/domains/add', methods=['POST'])
@login_required
def add_domain():
    domain_name = request.form.get('domain_name')
    from_address = request.form.get('from_address')
    if not domain_name or not from_address:
        flash('Domain name and from address are required', 'danger')
        return redirect(url_for('admin_domains'))
    if Domain.query.filter_by(domain_name=domain_name).first():
        flash('Domain already exists', 'danger')
        return redirect(url_for('admin_domains'))
    if not current_user.is_authenticated or not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('index'))
    d = Domain(domain_name=domain_name, from_address=from_address)
    db.session.add(d)
    db.session.commit()
    flash('Domain added', 'info')
    return redirect(url_for('admin_domains'))


@app.route('/admin/domains/add-prefix', methods=['POST'])
@login_required
def add_prefix():
    domain_id = request.form.get('domain_id')
    prefix = request.form.get('prefix')
    if not domain_id or not prefix:
        flash('Domain and prefix are required', 'danger')
        return redirect(url_for('admin_domains'))
    try:
        d = db.session.get(Domain, int(domain_id))
    except Exception:
        d = None
    if not d:
        flash('Domain not found', 'danger')
        return redirect(url_for('admin_domains'))
    # avoid duplicates
    if not current_user.is_authenticated or not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('index'))
    if DomainPrefix.query.filter_by(domain_id=d.id, prefix=prefix).first():
        flash('Prefix already exists for this domain', 'danger')
        return redirect(url_for('admin_domains'))
    p = DomainPrefix(domain_id=d.id, prefix=prefix)
    db.session.add(p)
    db.session.commit()
    flash('Prefix added', 'info')
    return redirect(url_for('admin_domains'))


@app.route('/admin/domains/delete', methods=['POST'])
@login_required
def delete_domain():
    if not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('index'))
    domain_id = request.form.get('domain_id')
    if not domain_id:
        flash('Domain id required', 'danger')
        return redirect(url_for('admin_domains'))
    try:
        d = db.session.get(Domain, int(domain_id))
    except Exception:
        d = None
    if not d:
        flash('Domain not found', 'danger')
        return redirect(url_for('admin_domains'))
    # check for any EmailQueue references
    ref_count = EmailQueue.query.filter_by(domain_id=d.id).count()
    if ref_count > 0:
        flash(f'Cannot delete domain: {ref_count} email(s) reference it. Reassign or delete those emails first.', 'danger')
        return redirect(url_for('admin_domains'))
    db.session.delete(d)
    db.session.commit()
    flash('Domain deleted', 'info')
    return redirect(url_for('admin_domains'))


@app.route('/templates', methods=['GET'])
@login_required
def templates_list():
    # show global templates and user's own
    templates = Template.query.filter((Template.owner_id == None) | (Template.owner_id == current_user.id)).order_by(Template.created_at.desc()).all()
    return render_template('templates_list.html', templates=templates)


@app.route('/templates/upload', methods=['POST'])
@login_required
def upload_template():
    name = request.form.get('name')
    is_global = bool(request.form.get('is_global'))
    file = request.files.get('template')
    if not name or not file:
        flash('name and template file required', 'danger')
        return redirect(url_for('templates_list'))
    html = file.read().decode('utf-8')
    owner_id = None if is_global and current_user.is_admin else current_user.id
    t = Template(name=name, owner_id=owner_id, html=html)
    db.session.add(t)
    db.session.commit()
    flash('Template saved', 'info')
    return redirect(url_for('templates_list'))


@app.route('/queue', methods=['GET'])
@login_required
def view_queue():
    f = request.args.get('filter', 'all')
    status = request.args.get('status')
    q = EmailQueue.query
    if f == 'mine':
        q = q.filter_by(user_id=current_user.id)
    if status:
        q = q.filter_by(status=status)
    emails = q.order_by(EmailQueue.created_at.desc()).limit(200).all()
    return render_template('queue.html', emails=emails, filter=f, status=status)


@app.route('/queue/stop-email', methods=['POST'])
@login_required
def stop_email():
    email_id = request.form.get('email_id')
    try:
        e = db.session.get(EmailQueue, int(email_id))
    except Exception:
        e = None
    if not e:
        flash('Email not found', 'danger')
        return redirect(url_for('view_queue'))
    # only owner or admin
    if e.user_id and e.user_id != current_user.id and not current_user.is_admin:
        flash('Not allowed', 'danger')
        return redirect(url_for('view_queue'))
    if e.status == 'queued' or e.status == 'sending':
        e.status = 'failed'
        e.response = 'Stopped by user'
        db.session.commit()
        flash('Email stopped', 'info')
    else:
        flash('Email cannot be stopped', 'warning')
    return redirect(url_for('view_queue'))


@app.route('/batches', methods=['GET'])
@login_required
def list_batches():
    # admins see all, users see their batches
    if current_user.is_admin:
        bs = Batch.query.order_by(Batch.created_at.desc()).all()
    else:
        bs = Batch.query.filter_by(created_by=current_user.id).order_by(Batch.created_at.desc()).all()
    # Annotate each batch with total and completed email counts.
    batches = []
    for b in bs:
        batch_emails = EmailQueue.query.filter_by(batch_id=b.id)
        total_emails = batch_emails.count()
        total_sent = batch_emails.filter_by(status='sent').count()
        batches.append({'id': b.id, 'creator': b.creator, 'total_emails': total_emails, 'total_sent': total_sent, 'paused': b.paused, 'stopped': b.stopped, 'created_at': b.created_at})
    return render_template('batches.html', batches=batches)


@app.route('/batches/<batch_id>', methods=['GET'])
@login_required
def batch_details(batch_id):
    batch = db.session.get(Batch, batch_id)
    if not batch:
        abort(404)
    if not current_user.is_admin and batch.created_by != current_user.id:
        abort(403)
    emails = EmailQueue.query.filter_by(batch_id=batch.id).order_by(EmailQueue.id.asc()).all()
    return render_template('result.html', batch=batch, emails=emails)


def _require_batch_control(b: Batch):
    if not b:
        return False
    if current_user.is_admin:
        return True
    return b.created_by == current_user.id


@app.route('/batch/pause', methods=['POST'])
@login_required
def pause_batch():
    batch_id = request.form.get('batch_id')
    b = db.session.get(Batch, batch_id)
    if not _require_batch_control(b):
        flash('Not allowed', 'danger')
        return redirect(url_for('list_batches'))
    b.paused = True
    db.session.commit()
    flash('Batch paused', 'info')
    return redirect(url_for('list_batches'))


@app.route('/batch/resume', methods=['POST'])
@login_required
def resume_batch():
    batch_id = request.form.get('batch_id')
    b = db.session.get(Batch, batch_id)
    if not _require_batch_control(b):
        flash('Not allowed', 'danger')
        return redirect(url_for('list_batches'))
    b.paused = False
    db.session.commit()
    flash('Batch resumed', 'info')
    return redirect(url_for('list_batches'))


@app.route('/batch/stop', methods=['POST'])
@login_required
def stop_batch():
    batch_id = request.form.get('batch_id')
    b = db.session.get(Batch, batch_id)
    if not _require_batch_control(b):
        flash('Not allowed', 'danger')
        return redirect(url_for('list_batches'))
    # mark batch stopped and mark queued emails failed
    b.stopped = True
    EmailQueue.query.filter_by(batch_id=b.id, status='queued').update({'status': 'failed', 'response': 'Stopped by user/admin'})
    db.session.commit()
    flash('Batch stopped', 'info')
    return redirect(url_for('list_batches'))


@app.route('/send', methods=['POST'])
@login_required
def send():
    prefix = request.form.get('prefix', 'hello')
    domain_id = request.form.get('domain')
    template_id = request.form.get('template_id')
    subject = request.form.get('subject', 'Hello from Flask')
    text = request.form.get('text', '')
    recipients_raw = request.form.get('recipients', '')
    recipients = [r.strip() for r in recipients_raw.splitlines() if r.strip()]
    try:
        domain = db.session.get(Domain, int(domain_id))
    except Exception:
        domain = None
    if not domain:
        flash('Invalid domain selected', 'danger')
        return redirect(url_for('index'))

    uploaded = request.files.get('template')
    if uploaded and uploaded.filename:
        html_content = uploaded.read().decode('utf-8')
    else:
        # if a template_id provided, use saved template
        if template_id:
            try:
                t = db.session.get(Template, int(template_id))
            except Exception:
                t = None
            html_content = t.html if t else request.form.get('template_text', '')
        else:
            uploaded = request.files.get('template')
            if uploaded and uploaded.filename:
                html_content = uploaded.read().decode('utf-8')
            else:
                html_content = request.form.get('template_text', '')

    api_key = os.environ.get('EMAIL_API_KEY')
    if not api_key:
        flash('EMAIL_API_KEY not set in environment', 'danger')
        return redirect(url_for('index'))

    url = "https://email.gofcom.com/v1/emails/send"
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    # create a batch id and insert EmailQueue rows for each recipient
    # create Batch record
    batch_id = str(uuid.uuid4())
    b = Batch(id=batch_id, created_by=(current_user.id if current_user.is_authenticated else None))
    db.session.add(b)
    db.session.flush()
    for email in recipients:
        eq = EmailQueue(batch_id=batch_id, user_id=(current_user.id if current_user.is_authenticated else None),
                        to_email=email, subject=subject, text=text, html=html_content,
                        template_id=(template_id if template_id else None), domain_id=domain.id,
                        from_prefix=prefix, status='queued')
        db.session.add(eq)
    db.session.commit()
    return redirect(url_for('batch_details', batch_id=batch_id))


if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1')
