# =========================================
# Jamat Movement WA - Flask App
# =========================================

import os
os.chdir(r"H:\Jamat Movement App")  # change to the folder with app.py and templates

from flask import Flask, render_template, request, redirect, flash, send_file, Response
import sqlite3
from threading import Thread
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import io
import base64
from functools import wraps

# -----------------------------
# Configuration
# -----------------------------
BASE_DIR = r"H:\Jamat Movement App"
os.makedirs(BASE_DIR, exist_ok=True)

DATABASE_URL = os.path.join(BASE_DIR, "branch_visits.db")
WA_MOSQUES_CSV = os.path.join(BASE_DIR, "wa_mosques.csv")
EXTERNAL_JAMAT_CSV = os.path.join(BASE_DIR, "external_jamat.csv")

SECRET_KEY = "75312016490dd898f787de9ead348679"
APP_USERNAME = "tashkil"
APP_PASSWORD = "427@WStreet"

# -----------------------------
# Flask App
# -----------------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY

# -----------------------------
# Authentication
# -----------------------------
def check_auth(username, password):
    return username == APP_USERNAME and password == APP_PASSWORD

def authenticate():
    return Response(
        'Authentication required', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# -----------------------------
# Database Helper
# -----------------------------
def get_db():
    return sqlite3.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Drop old tables to avoid schema conflicts
    c.execute("DROP TABLE IF EXISTS mosque")
    c.execute("DROP TABLE IF EXISTS external_jamat")
    c.execute("DROP TABLE IF EXISTS visits")

    # Create mosque table
    c.execute('''
    CREATE TABLE mosque (
        mosque_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        address TEXT,
        phone TEXT,
        notes TEXT
    )
    ''')

    # Create external_jamat table
    c.execute('''
    CREATE TABLE external_jamat (
        ej_id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT,
        name TEXT
    )
    ''')

    # Create visits table
    c.execute('''
    CREATE TABLE visits (
        visit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_mosque_id INTEGER,
        visiting_mosque_id INTEGER,
        visiting_jamat_id INTEGER,
        start_date TEXT,
        end_date TEXT,
        notes TEXT
    )
    ''')

    # Populate mosques from CSV
    if os.path.exists(WA_MOSQUES_CSV):
        df = pd.read_csv(WA_MOSQUES_CSV)
        df.to_sql('mosque', conn, if_exists='append', index=False)

    # Populate external_jamat from CSV
    if os.path.exists(EXTERNAL_JAMAT_CSV):
        df = pd.read_csv(EXTERNAL_JAMAT_CSV)
        df.to_sql('external_jamat', conn, if_exists='append', index=False)

    conn.commit()
    conn.close()
    print("Database initialized successfully!")

# Initialize DB
init_db()

# -----------------------------
# Routes
# -----------------------------

# Home
@app.route('/')
def index():
    return redirect('/dashboard')

# Add Visit
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
        notes = request.form.get('notes', '')

        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')

        # Check overlapping bookings
        c.execute('''
            SELECT * FROM visits WHERE host_mosque_id=? AND 
            ((start_date <= ? AND end_date >= ?) OR
             (start_date <= ? AND end_date >= ?))
        ''', (host_mosque, start_date.strftime('%Y-%m-%d'), start_date.strftime('%Y-%m-%d'),
              end_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')))
        overlaps = c.fetchall()
        if overlaps:
            flash("Warning: This mosque already has a booking in this range!", "warning")

        # Insert visit
        c.execute('''
            INSERT INTO visits (host_mosque_id, visiting_mosque_id, visiting_jamat_id, start_date, end_date, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (host_mosque, visiting_mosque, visiting_jamat, start_date.strftime('%Y-%m-%d'),
              end_date.strftime('%Y-%m-%d'), notes))
        conn.commit()
        conn.close()
        flash("Visit added successfully!", "success")
        return redirect('/add_visit')

    return render_template("add_visit.html", mosques=mosques, ej_options=ej_options)

# Dashboard Route
@app.route('/dashboard', methods=['GET','POST'])
@requires_auth
def dashboard():
    conn = get_db()
    conn.row_factory = sqlite3.Row  # Access columns by name
    c = conn.cursor()

    # -----------------------------
    # Filter inputs (must be before queries)
    # -----------------------------
    start_date = request.form.get('start_date', '2025-01-01')
    end_date = request.form.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    host_filter = request.form.get('host_filter', 'all')
    visiting_filter = request.form.get('visiting_filter', 'all')

    # Get all mosques for host filter dropdown 
    c.execute("SELECT mosque_id, name FROM mosque") 
    mosques = c.fetchall()

    # Get only visiting mosques that have visits in the selected date range
    visiting_query = '''
        SELECT DISTINCT m2.mosque_id, m2.name
        FROM visits v
        JOIN mosque m2 ON v.visiting_mosque_id = m2.mosque_id
        WHERE v.start_date BETWEEN ? AND ?
    '''
    c.execute(visiting_query, (start_date, end_date))
    visiting_mosques = c.fetchall()

    # -----------------------------
    # SQL query for visits with optional filters
    # -----------------------------
    query = '''
        SELECT v.visit_id, v.start_date, v.end_date,
               m1.name as host, m2.name as visiting_mosque,
               ej.name as visiting_jamat, v.notes
        FROM visits v
        LEFT JOIN mosque m1 ON v.host_mosque_id = m1.mosque_id
        LEFT JOIN mosque m2 ON v.visiting_mosque_id = m2.mosque_id
        LEFT JOIN external_jamat ej ON v.visiting_jamat_id = ej.ej_id
        WHERE v.start_date BETWEEN ? AND ?
    '''
    params = [start_date, end_date]

    if host_filter != 'all':
        query += " AND v.host_mosque_id=?"
        params.append(host_filter)
    if visiting_filter != 'all':
        query += " AND v.visiting_mosque_id=?"
        params.append(visiting_filter)

    c.execute(query, params)
    visits = c.fetchall()

    # -----------------------------
    # Generate Horizontal Bar Charts
    # -----------------------------
    host_counts = {}
    visiting_counts = {}

    for v in visits:
        host = v['host'] or "Unknown"
        visiting = v['visiting_mosque'] or "Unknown"
        host_counts[host] = host_counts.get(host, 0) + 1
        visiting_counts[visiting] = visiting_counts.get(visiting, 0) + 1

    def create_hbar_chart(data_dict):
        if not data_dict:
            return None
        plt.figure(figsize=(6,4))
        names = list(data_dict.keys())
        counts = list(data_dict.values())
        plt.barh(names, counts, color='skyblue')
        plt.xlabel("Number of Jamats")
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        return base64.b64encode(buf.getvalue()).decode('utf-8')

    host_chart = create_hbar_chart(host_counts)
    visiting_chart = create_hbar_chart(visiting_counts)

    conn.close()

    return render_template(
        "dashboard.html",
        visits=visits,
        start_date=start_date,
        end_date=end_date,
        mosques=mosques,
        visiting_mosques=visiting_mosques,
        host_filter=str(host_filter),
        visiting_filter=str(visiting_filter),
        host_chart=host_chart,
        visiting_chart=visiting_chart
    )


# -----------------------------
# Mosques List
# -----------------------------
@app.route('/mosques')
@requires_auth
def mosques():
    conn = get_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT mosque_id, name, address, phone, notes FROM mosque ORDER BY name")
    rows = c.fetchall()
    conn.close()
    return render_template('mosques.html', mosques=rows)



# -----------------------------
# Mosque Detail
# -----------------------------
@app.route('/mosque/<int:mosque_id>')
@requires_auth
def mosque_detail(mosque_id):
    conn = get_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Get mosque info
    c.execute("SELECT * FROM mosque WHERE mosque_id=?", (mosque_id,))
    mosque = c.fetchone()

    # Get visits hosted by this mosque
    c.execute('''
        SELECT v.start_date, v.end_date, m2.name as visiting_mosque, ej.name as visiting_jamat, v.notes
        FROM visits v
        LEFT JOIN mosque m2 ON v.visiting_mosque_id = m2.mosque_id
        LEFT JOIN external_jamat ej ON v.visiting_jamat_id = ej.ej_id
        WHERE v.host_mosque_id=?
        ORDER BY v.start_date
    ''', (mosque_id,))
    visits = c.fetchall()

    conn.close()
    return render_template("mosque_detail.html", mosque=mosque, visits=visits)


# -----------------------------
# Contact US
# -----------------------------
@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        message = request.form.get('message')

        # For now, just flash success (can be saved to DB or emailed later)
        flash("Thank you for contacting us! We'll review your message shortly.", "success")
        return redirect('/contact')

    return render_template("contact.html")


# -----------------------------
# Run Flask in Jupyter
# -----------------------------
def run_app():
    app.run(debug=True, use_reloader=False)

Thread(target=run_app).start()
