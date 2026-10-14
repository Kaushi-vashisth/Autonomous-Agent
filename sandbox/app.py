"""Mock helpdesk (Flask + SQLite) with injected failures for the operator demo.

Injected behaviours (when SANDBOX_FAULTS=1, the default):
  * The refund form hints MM/DD/YYYY but the server only accepts YYYY-MM-DD (date-format error).
  * The first otherwise-valid refund POST returns a one-time HTTP 500 (nothing is saved).
  * Duplicate (customer, refund number) pairs are rejected.
"""
import argparse
import os
import re
import sqlite3
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)

BASE = Path(__file__).parent
DB = os.getenv("SANDBOX_DB", str(BASE / "helpdesk.db"))
FAULTS = os.getenv("SANDBOX_FAULTS", "1") == "1"
FAULT_STATE = {"server_error_done": False}

CUSTOMERS = ["Northwind Traders", "Northwind Logistics", "Contoso Ltd", "Fabrikam Inc"]
TICKETS = [  # ticket_number, customer, opened_date
    ("TCK-7001", "Contoso Ltd", "2026-01-05"),
    ("TCK-7002", "Contoso Ltd", "2026-02-20"),
    ("TCK-7003", "Contoso Ltd", "2026-03-12"),
    ("TCK-4410", "Northwind Traders", "2026-03-01"),
    ("TCK-9100", "Fabrikam Inc", "2026-02-02"),
]

app = Flask(__name__)
app.secret_key = "sandbox-only-not-secret"


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db(reset=False):
    if reset and os.path.exists(DB):
        os.remove(DB)
    conn = sqlite3.connect(DB)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS refunds(
        id INTEGER PRIMARY KEY AUTOINCREMENT, customer TEXT, refund_number TEXT,
        amount REAL, respond_by TEXT, UNIQUE(customer, refund_number));
    CREATE TABLE IF NOT EXISTS tickets(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_number TEXT UNIQUE, customer TEXT,
        opened_date TEXT, status TEXT DEFAULT 'open');
    """)
    if conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0:
        conn.executemany("INSERT INTO tickets(ticket_number, customer, opened_date) VALUES (?,?,?)", TICKETS)
    conn.commit()
    conn.close()


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


@app.route("/")
def index():
    return redirect(url_for("customers"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == "demo" and request.form.get("password") == "demo123":
            session["user"] = "demo"
            return redirect(url_for("customers"))
        flash("Invalid username or password.", "err")
    return render_template("login.html")


@app.route("/customers")
@login_required
def customers():
    return render_template("customers.html", customers=CUSTOMERS)


@app.route("/refunds")
@login_required
def refunds():
    rows = db().execute("SELECT * FROM refunds ORDER BY id").fetchall()
    return render_template("refunds.html", rows=rows)


@app.route("/refunds/new", methods=["GET", "POST"])
@login_required
def new_refund():
    form = request.form if request.method == "POST" else {}
    if request.method == "POST":
        customer = form.get("customer", "").strip()
        number = form.get("refund_number", "").strip()
        amount = form.get("amount", "").strip()
        due = form.get("respond_by", "").strip()
        error = None
        if customer not in CUSTOMERS or not number or not amount or not due:
            error = "All fields are required and the customer must be in the customer list."
        elif not re.fullmatch(r"\d+(\.\d{1,2})?", amount):
            error = "Amount must be a plain number such as 1234.50 (no currency symbol or commas)."
        elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
            error = "Invalid respond-by date format. Use YYYY-MM-DD."
        elif db().execute("SELECT 1 FROM refunds WHERE customer=? AND refund_number=?",
                          (customer, number)).fetchone():
            error = f"Duplicate refund: {number} already exists for {customer}."
        if error:
            flash(error, "err")
        else:
            if FAULTS and not FAULT_STATE["server_error_done"]:
                FAULT_STATE["server_error_done"] = True
                abort(500)
            cur = db().execute(
                "INSERT INTO refunds(customer, refund_number, amount, respond_by) VALUES (?,?,?,?)",
                (customer, number, float(amount), due))
            db().commit()
            flash(f"Refund {number} saved.", "ok")
            return redirect(url_for("refund_detail", refund_id=cur.lastrowid))
    return render_template("refund_form.html", customers=CUSTOMERS, form=form, faults=FAULTS)


@app.route("/refunds/<int:refund_id>")
@login_required
def refund_detail(refund_id):
    row = db().execute("SELECT * FROM refunds WHERE id=?", (refund_id,)).fetchone()
    if not row:
        abort(404)
    return render_template("refund_detail.html", r=row)


@app.route("/tickets")
@login_required
def tickets():
    rows = db().execute("SELECT * FROM tickets ORDER BY id").fetchall()
    return render_template("tickets.html", rows=rows)


@app.route("/tickets/<int:ticket_id>")
@login_required
def ticket_detail(ticket_id):
    row = db().execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
    if not row:
        abort(404)
    return render_template("ticket_detail.html", r=row)


@app.route("/tickets/<int:ticket_id>/resolve", methods=["POST"])
@login_required
def ticket_resolve(ticket_id):
    row = db().execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
    if not row:
        abort(404)
    if row["status"] == "resolved":
        flash("Ticket is already marked resolved.", "err")
    else:
        db().execute("UPDATE tickets SET status='resolved' WHERE id=?", (ticket_id,))
        db().commit()
        flash(f"{row['ticket_number']} marked as resolved.", "ok")
    return redirect(url_for("ticket_detail", ticket_id=ticket_id))


@app.route("/api/stats")
def stats():
    c = db()
    return jsonify(
        refunds=c.execute("SELECT COUNT(*) FROM refunds").fetchone()[0],
        tickets_resolved=c.execute("SELECT COUNT(*) FROM tickets WHERE status='resolved'").fetchone()[0],
        refund_rows=[dict(r) for r in c.execute("SELECT * FROM refunds ORDER BY id")],
        resolved_tickets=[r["ticket_number"] for r in c.execute("SELECT ticket_number FROM tickets WHERE status='resolved'")],
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5001)
    ap.add_argument("--reset", action="store_true", help="recreate the database")
    args = ap.parse_args()
    init_db(reset=args.reset)
    app.run(host="127.0.0.1", port=args.port, debug=False)
