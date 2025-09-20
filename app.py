import os
import sqlite3
from flask import Flask, render_template, request, redirect, flash, session
from datetime import datetime, timedelta
from functools import wraps

# -----------------------------
# Environment variables
# -----------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "dev_secret_key")  # default for local testing
DATABASE_URL = os.environ.get("DATABASE_URL", "branch_visits.db")  # default SQLite local

# -----------------------------
# Flask App
# -----------------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY

# -----------------------------
# Basic Authentication
# -----------------------------
USERNAME = os.environ.get("APP_USERNAME", "admin")
PASSWORD = os.environ.get("APP_PASSWORD", "password")

def check_auth(username, password):
    return username == USERNAME and password == PASSWORD

def authenticate():
    return "Unauthorized access", 401, {'WWW-Authenticate': 'Basic realm="Login Required"'}

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# -----------------------------
# Database connection
# -----------------------------
def get_db():
    if DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://"):
        import psycopg2
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        return sqlite3.connect(DATABASE_URL)

# -----------------------------
# Initialize database (SQLite only)
# -----------------------------
def init_db():
    if DATABASE_URL.endswith(".db"):
        conn = get_db()
        c = conn.cursor()

        # Drop tables if exist
        c.execute("DROP TABLE IF EXISTS mosque")
        c.execute("DROP TABLE IF EXISTS external_jamat")
        c.execute("DROP TABLE IF EXISTS visits")

        # Create tables
        c.execute("""
        CREATE TABLE mosque (
            mosque_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            address TEXT,
            phone TEXT,
            email TEXT
        )
        """)
        c.execute("""
        CREATE TABLE external_jamat (
            ej_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT
        )
        """)
        c.execute("""
        CREATE TABLE visits (
            visit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_mosque_id INTEGER,
            visiting_mosque_id INTEGER,
            visiting_jamat_id INTEGER,
            start_date TEXT,
            end_date TEXT,
            notes TEXT
        )
        """)
        conn.commit()
        conn.close()
        print("Database initialized!")

# -----------------------------
# Routes
# -----------------------------
@app.route('/')
@requires_auth
def index():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT mosque_id, name FROM mosque")
    mosques = c.fetchall()
    return render_template('index.html', mosques=mosques)

@app.route('/add_visit', methods=['GET','POST'])
@requires_auth
def add_visit():
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT mosque_id, name FROM mosque")
    mosques = c.fetchall()

    c.execute("SELECT ej_id, name FROM external_jamat")
    ej_options = c.fetchall()

    if request.method == 'POST':
        host_mosque = request.form['host_mosque']
        visiting_mosque = request.form.get('visiting_mosque') or None
        visiting_jamat = request.form.get('visiting_jamat') or None
        notes = request.form['notes']

        start_date_str = request.form['start_date']
        end_date_str = request.form['end_date']

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')

        # Insert one row per day in the range
        delta = end_date - start_date
        for i in range(delta.days + 1):
            visit_date = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
            c.execute("""
                INSERT INTO visits (host_mosque_id, visiting_mosque_id, visiting_jamat_id, start_date, end_date, notes)
                VALUES (?,?,?,?,?,?)
            """, (host_mosque, visiting_mosque, visiting_jamat, start_date_str, end_date_str, notes))

        conn.commit()
        conn.close()
        flash("Visit added successfully!", "success")
        return redirect('/add_visit')

    return render_template('add_visit.html', mosques=mosques, ej_options=ej_options)

@app.route('/dashboard', methods=['GET','POST'])
@requires_auth
def dashboard():
    conn = get_db()
    c = conn.cursor()

    start_date = request.form.get('start_date', '2025-01-01')
    end_date = request.form.get('end_date', datetime.today().strftime('%Y-%m-%d'))

    c.execute("""
        SELECT v.visit_id, m.name as host, vm.name as visitor_mosque, ej.name as visitor_jamat, v.start_date, v.end_date, v.notes
        FROM visits v
        LEFT JOIN mosque m ON v.host_mosque_id = m.mosque_id
        LEFT JOIN mosque vm ON v.visiting_mosque_id = vm.mosque_id
        LEFT JOIN external_jamat ej ON v.visiting_jamat_id = ej.ej_id
        WHERE v.start_date BETWEEN ? AND ?
        ORDER BY v.start_date ASC
    """, (start_date, end_date))
    visits = c.fetchall()
    conn.close()

    return render_template('dashboard.html', visits=visits, start_date=start_date, end_date=end_date)

# -----------------------------
# Run Flask app
# -----------------------------
if __name__ == "__main__":
    if DATABASE_URL.endswith(".db"):
        init_db()  # initialize SQLite only
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
