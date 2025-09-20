# =========================================
# Jamat Movement WA - Flask Routes
# =========================================
from flask import Flask, render_template, request, redirect, flash, send_file, Response
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import io
import base64
import matplotlib.pyplot as plt
from functools import wraps
from threading import Thread

# Use the same app from the previous cell
# app = Flask(__name__)
# app.secret_key = SECRET_KEY

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

# Dashboard
@app.route('/dashboard', methods=['GET','POST'])
@requires_auth
def dashboard():
    conn = get_db()
    c = conn.cursor()

    start_date = request.form.get('start_date', '2025-01-01')
    end_date = request.form.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    host_filter = request.form.get('host_filter', 'all')

    query = '''
    SELECT v.visit_id, v.start_date, v.end_date, m1.name as host, 
           m2.name as visiting_mosque, ej.name as visiting_jamat, v.notes 
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

    c.execute(query, params)
    visits = c.fetchall()
    conn.close()

    return render_template("dashboard.html",
                           visits=visits,
                           start_date=start_date,
                           end_date=end_date)

# -----------------------------
# Run Flask in Jupyter
# -----------------------------
def run_app():
    app.run(debug=True, use_reloader=False)

Thread(target=run_app).start()
