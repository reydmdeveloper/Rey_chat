"""
REYDM – REY Datamind Multi-Tool Platform
Flask + MySQL + Email Notifications
Tools: Reminder, Night Shift, Attendance, Petty Cash (CBE/DGL), Leave Manager,
       Char Palette, Cost Converter, Project Analysis, PDF Unlocker
"""

import os
import sys

# Reconfigure stdout and stderr to UTF-8 to prevent emoji print crashes on Windows CP1252
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
except Exception:
    pass

import json
import random
import string
import threading
import time
import re as re_module
from datetime import datetime, timedelta, date
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory, send_file
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, emit, join_room
import uuid
import mysql.connector
import pytz

# ─── Timezone (IST) ──────────────────────────────────────────────────
IST = pytz.timezone("Asia/Kolkata")


def now_ist():
    """Return current naive datetime in IST (no tzinfo, MySQL-friendly)."""
    return datetime.now(IST).replace(tzinfo=None)


def today_ist():
    """Return today's date in IST."""
    return now_ist().date()


# ─── App Configuration ───────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-to-a-random-secret-key")
app.permanent_session_lifetime = timedelta(days=365)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload

@app.after_request
def add_header(r):
    """Add headers to prevent caching of dynamic pages in WebViews"""
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    return r


# Storage directory for local uploads (C:\rey_chat or local workspace fallback)
UPLOAD_FOLDER = r"C:\rey_chat"
try:
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except Exception:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), "rey_chat")
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Force PyInstaller to bundle Flask-SocketIO's dynamic/hidden imports
import engineio.async_drivers.threading
import simple_websocket

# Initialize SocketIO for real-time WhatsApp-like features
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Real-time state tracking
online_users = {}        # user_id (int) -> set of socket sids
sid_to_uid = {}          # sid -> user_id (int)
user_active_room = {}    # sid -> room_id (str)
user_custom_statuses = {} # user_id (int) -> 'online' | 'away' | 'offline'

# ─── Database Configuration ──────────────────────────────────────────
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "mysql-21f1e29c-reydmdeveloper-2e13.i.aivencloud.com"),
    "port": int(os.environ.get("DB_PORT", 17090)),
    "user": os.environ.get("DB_USER", "avnadmin"),
    "password": os.environ.get("DB_PASSWORD", "AVNS_l-v67tdYKfQUCJZmrp9"),
    "database": os.environ.get("DB_NAME", "reydm_db"),
}

# ─── Email Configuration ─────────────────────────────────────────────
GMAIL_USER = os.environ.get("GMAIL_USER", "reydmdeveloper@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "txebwrbrwtvuqttc")
# SMTP transport: 'ssl' (port 465) by default — Render free tier blocks port 587 STARTTLS,
# but port 465 SSL works reliably. Set SMTP_MODE=starttls to force port 587.
SMTP_MODE = os.environ.get("SMTP_MODE", "ssl").lower()

# ─── Available Tools (Chat removed) ──────────────────────────────────
AVAILABLE_TOOLS = {
    "reminder": {
        "name": "Reminder",
        "icon": "fa-solid fa-bell",
        "description": "Project reminder with countdown & email alerts",
    },
    "nightshift": {
        "name": "Night Shift",
        "icon": "fa-solid fa-moon",
        "description": "Night shift attendance tracker with dashboard",
    },
    "charpalette": {
        "name": "Char Palette",
        "icon": "fa-solid fa-font",
        "description": "Unicode character palette with search & copy",
    },
    "costconverter": {
        "name": "Cost Converter",
        "icon": "fa-solid fa-money-bill-transfer",
        "description": "Currency exchange rate converter",
    },
    "projectanalysis": {
        "name": "Project Analysis",
        "icon": "fa-solid fa-file-pdf",
        "description": "PDF project analyzer with export",
    },
    "pdfunlocker": {
        "name": "PDF Unlocker",
        "icon": "fa-solid fa-lock-open",
        "description": "Remove restrictions from PDF files",
    },
    "attendance": {
        "name": "Attendance",
        "icon": "fa-solid fa-clock",
        "description": "Login/Logout time tracker with reports",
    },
    "pettycash_cbe": {
        "name": "Petty Cash (CBE)",
        "icon": "fa-solid fa-money-bill-wave",
        "description": "Coimbatore office petty cash tracker",
    },
    "pettycash_dgl": {
        "name": "Petty Cash (DGL)",
        "icon": "fa-solid fa-money-bills",
        "description": "Dindigul office petty cash tracker",
    },
    "leavemanager": {
        "name": "Leave Manager",
        "icon": "fa-solid fa-calendar-check",
        "description": "Employee leave tracker with monthly dashboard",
    },
    "chat": {
        "name": "Secure Chat",
        "icon": "fa-solid fa-comments",
        "description": "Real-time secure messaging",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# DATABASE HELPERS
# ═══════════════════════════════════════════════════════════════════════

def get_db():
    """Get a database connection with IST timezone set."""
    try:
        conn = mysql.connector.connect(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            connection_timeout=10,
        )
        cur = conn.cursor()
        cur.execute("SET time_zone = '+05:30'")
        cur.close()
        return conn
    except mysql.connector.Error as e:
        print(f"❌ Database connection error: {e}")
        return None


def init_db():
    """Create the database and tables if they don't exist."""
    try:
        conn = mysql.connector.connect(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
        )
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_CONFIG['database']}`")
        cur.execute(f"USE `{DB_CONFIG['database']}`")
        cur.execute("SET time_zone = '+05:30'")

        # ─── USERS ───────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                full_name VARCHAR(100) NOT NULL,
                email VARCHAR(150) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role ENUM('admin', 'user') DEFAULT 'user',
                is_approved TINYINT(1) DEFAULT 0,
                is_active TINYINT(1) DEFAULT 1,
                mail_enabled TINYINT(1) DEFAULT 1,
                allowed_tools JSON DEFAULT NULL,
                last_active DATETIME DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)

        # Add avatar_url column to users if it doesn't exist
        try:
            cur.execute("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(255) DEFAULT NULL")
        except Exception:
            pass

        # Add about column to users if it doesn't exist
        try:
            cur.execute("ALTER TABLE users ADD COLUMN about VARCHAR(255) DEFAULT 'Available'")
        except Exception:
            pass

        # ─── OTP ─────────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS otp_tokens (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(150) NOT NULL,
                otp_code VARCHAR(6) NOT NULL,
                purpose ENUM('register', 'reset_password') DEFAULT 'register',
                is_used TINYINT(1) DEFAULT 0,
                expires_at DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ─── REMINDERS ───────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INT AUTO_INCREMENT PRIMARY KEY,
                project_name VARCHAR(255) NOT NULL,
                reminder_datetime DATETIME NOT NULL,
                created_by INT NOT NULL,
                is_sent TINYINT(1) DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE KEY unique_project_time (project_name, reminder_datetime)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS reminder_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                reminder_id INT NOT NULL,
                sent_to VARCHAR(150) NOT NULL,
                status ENUM('sent', 'failed') DEFAULT 'sent',
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (reminder_id) REFERENCES reminders(id) ON DELETE CASCADE
            )
        """)

        # ─── NIGHT SHIFT ─────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ns_employees (
                id INT AUTO_INCREMENT PRIMARY KEY,
                emp_id VARCHAR(20) UNIQUE NOT NULL,
                name VARCHAR(100) NOT NULL,
                dept VARCHAR(60) DEFAULT '',
                status ENUM('active', 'resigned') DEFAULT 'active',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS ns_attendance (
                id INT AUTO_INCREMENT PRIMARY KEY,
                emp_id VARCHAR(20) NOT NULL,
                att_date DATE NOT NULL,
                present TINYINT(1) DEFAULT 1,
                UNIQUE KEY unique_emp_date (emp_id, att_date)
            )
        """)

        # ─── ATTENDANCE LOGS ─────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS attendance_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                login_date DATE NOT NULL,
                login_time DATETIME NOT NULL,
                logout_time DATETIME DEFAULT NULL,
                hours_spent DECIMAL(5,2) DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE KEY unique_user_date (user_id, login_date)
            )
        """)

        # Add unique index if missing (for older DBs)
        try:
            cur.execute("ALTER TABLE attendance_logs ADD UNIQUE KEY unique_user_date (user_id, login_date)")
        except mysql.connector.Error:
            pass

        cur.execute("""
            CREATE TABLE IF NOT EXISTS attendance_requests (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                request_date DATE NOT NULL,
                requested_login DATETIME NOT NULL,
                requested_logout DATETIME NOT NULL,
                reason VARCHAR(500) DEFAULT '',
                status ENUM('pending', 'approved', 'declined') DEFAULT 'pending',
                admin_note VARCHAR(255) DEFAULT '',
                reviewed_by INT DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # ─── PETTY CASH (CBE + DGL) ──────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS petty_cash (
                id INT AUTO_INCREMENT PRIMARY KEY,
                office ENUM('cbe', 'dgl') NOT NULL,
                entry_date DATE NOT NULL,
                particular VARCHAR(500) NOT NULL,
                amount DECIMAL(12,2) NOT NULL,
                entry_type ENUM('credit', 'debit') NOT NULL,
                category VARCHAR(80) DEFAULT '',
                created_by INT DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_office_date (office, entry_date)
            )
        """)

        # ─── LEAVE MANAGER ───────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lm_employees (
                id INT AUTO_INCREMENT PRIMARY KEY,
                sno INT DEFAULT 0,
                emp_id VARCHAR(30) UNIQUE NOT NULL,
                name VARCHAR(150) NOT NULL,
                dept VARCHAR(60) DEFAULT '',
                status ENUM('Active', 'Inactive') DEFAULT 'Active',
                join_date DATE DEFAULT NULL,
                extra_cl DECIMAL(5,2) DEFAULT 0,
                extra_sl DECIMAL(5,2) DEFAULT 0,
                extra_note VARCHAR(255) DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS lm_leaves (
                id INT AUTO_INCREMENT PRIMARY KEY,
                emp_id VARCHAR(30) NOT NULL,
                yr INT NOT NULL,
                mon VARCHAR(5) NOT NULL,
                dy INT NOT NULL,
                lv_type VARCHAR(4) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_emp_date (emp_id, yr, mon, dy),
                INDEX idx_year (yr)
            )
        """)

        # ─── ADMIN SETTINGS ──────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_settings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                setting_key VARCHAR(100) UNIQUE NOT NULL,
                setting_value TEXT DEFAULT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)

        # ─── CHAT MESSAGES ───────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INT AUTO_INCREMENT PRIMARY KEY,
                conversation_id VARCHAR(100) NOT NULL,
                sender_id INT NOT NULL,
                message_text TEXT,
                message_type ENUM('text', 'file') DEFAULT 'text',
                file_url VARCHAR(255) DEFAULT NULL,
                file_name VARCHAR(255) DEFAULT NULL,
                reply_to_id INT DEFAULT NULL,
                is_pinned BOOLEAN DEFAULT 0,
                is_forwarded BOOLEAN DEFAULT 0,
                status ENUM('sent', 'delivered', 'read') DEFAULT 'sent',
                is_edited BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_conversation_id (conversation_id),
                INDEX idx_sender_id (sender_id),
                INDEX idx_created_at (created_at),
                INDEX idx_status (status)
            )
        """)
        
        try:
            cur.execute("ALTER TABLE messages ADD COLUMN is_forwarded BOOLEAN DEFAULT 0")
        except Exception:
            pass

        try:
            cur.execute("ALTER TABLE messages ADD COLUMN status ENUM('sent', 'delivered', 'read') DEFAULT 'sent'")
        except Exception:
            pass

        try:
            cur.execute("ALTER TABLE messages ADD COLUMN is_edited BOOLEAN DEFAULT 0")
        except Exception:
            pass

        try:
            cur.execute("ALTER TABLE messages ADD COLUMN delivered_at DATETIME DEFAULT NULL")
        except Exception:
            pass

        try:
            cur.execute("ALTER TABLE messages ADD COLUMN read_at DATETIME DEFAULT NULL")
        except Exception:
            pass
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_groups (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                created_by INT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_group_members (
                group_id INT NOT NULL,
                user_id INT NOT NULL,
                last_read_at DATETIME DEFAULT NULL,
                PRIMARY KEY (group_id, user_id),
                FOREIGN KEY (group_id) REFERENCES chat_groups(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Add role column to chat_group_members if it doesn't exist
        try:
            cur.execute("ALTER TABLE chat_group_members ADD COLUMN role ENUM('admin','member') DEFAULT 'member'")
        except Exception:
            pass

        # ─── MESSAGE REACTIONS ──────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS message_reactions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                message_id INT NOT NULL,
                user_id INT NOT NULL,
                emoji VARCHAR(10) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_reaction (message_id, user_id, emoji),
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # ─── PER-MESSAGE READ RECEIPTS (group chats) ─────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS message_read_receipts (
                message_id INT NOT NULL,
                user_id    INT NOT NULL,
                read_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (message_id, user_id),
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id)    REFERENCES users(id)    ON DELETE CASCADE
            )
        """)

        # ─── PINNED CONVERSATIONS ───────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pinned_conversations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                conversation_id VARCHAR(100) NOT NULL,
                pinned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_pin (user_id, conversation_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # ─── USER CONVERSATION CLEARED ──────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_conversation_cleared (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                conversation_id VARCHAR(100) NOT NULL,
                cleared_up_to_message_id INT DEFAULT 0,
                cleared_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_user_convo (user_id, conversation_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # ─── DELETED MESSAGES FOR USER ──────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS deleted_messages_for_user (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                message_id INT NOT NULL,
                deleted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_user_msg (user_id, message_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
            )
        """)

        # ─── Default admin ───────────────────────────────────────────
        cur.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        if not cur.fetchone():
            admin_hash = generate_password_hash("admin123")
            all_tools = json.dumps(list(AVAILABLE_TOOLS.keys()))
            cur.execute(
                """INSERT INTO users (full_name, email, password_hash, role, is_approved, allowed_tools)
                   VALUES (%s, %s, %s, 'admin', 1, %s)""",
                ("Administrator", "admin@system.local", admin_hash, all_tools),
            )

        # ─── Default night shift employees ───────────────────────────
        cur.execute("SELECT COUNT(*) FROM ns_employees")
        if cur.fetchone()[0] == 0:
            defaults = [
                ('E001', 'Ashwath', '', 'active'),
                ('E002', 'Bharathi', '', 'active'),
                ('E003', 'Dharani', '', 'active'),
                ('E004', 'Kanchana', '', 'active'),
                ('E005', 'Karthikeyan', '', 'active'),
                ('E006', 'Nethra', '', 'active'),
                ('E007', 'Sanjay', '', 'active'),
                ('E008', 'SRK', '', 'active'),
            ]
            cur.executemany(
                "INSERT INTO ns_employees (emp_id, name, dept, status) VALUES (%s, %s, %s, %s)",
                defaults,
            )

        # ─── Default leave manager employees ─────────────────────────
        cur.execute("SELECT COUNT(*) FROM lm_employees")
        if cur.fetchone()[0] == 0:
            lm_defaults = [
                (1, 'RDM1001', 'NANDHINI M', 'QC'),
                (2, 'RDM1002', 'MANOJ KUMAR P', 'Process'),
                (3, 'RDM1003', 'RAJALAKSHMI M', 'QC'),
                (4, 'RDM1004', 'DHARANI M', 'Process'),
                (5, 'RDM1005', 'SANJAY K', 'Process'),
                (6, 'RDM1006', 'VIJAY G', 'Process'),
                (7, 'RDM1007', 'MANOJ M', 'Process'),
                (8, 'RDM1008', 'SANJAY RAJAKUMARAN S', 'Process'),
                (9, 'RDM1009', 'PANDI SUBIKSHA G', 'Process'),
                (10, 'RDM1010', 'DIVYA K', 'QC'),
                (11, 'RDM1011', 'MUTHURAMAN S', 'Process'),
                (12, 'RDM1012', 'SAKTHI CHANDHANA S', 'Process'),
                (13, 'RDM1013', 'ASHWATH S', 'QC'),
                (14, 'RDM1014', 'BHARATHI PRIYADHARSHINI S', 'QC'),
                (15, 'RDM1015', 'KISHORE KUMAR K', 'Process'),
                (16, 'RDM1016', 'NANDHA KUMAR B', 'Process'),
                (17, 'RDM1017', 'THARANI D', 'QC'),
                (18, 'RDM1018', 'DIVYA M', 'QC'),
                (19, 'RDM1019', 'KANCHANA P', 'QC'),
                (20, 'RDM1020', 'ASWINI SHANU S', 'QC'),
                (21, 'RDM1021', 'KARTHIKEYAN N', 'QC'),
                (22, 'RDM1022', 'SURYA S', 'Process'),
                (23, 'RDM1023', 'SRIRAM S', 'Process'),
                (24, 'RDM1024', 'RAJALAKSHMI S', 'QC'),
                (25, 'RDM1025', 'LILASRI RAVIKUMAR', 'Process'),
            ]
            cur.executemany(
                "INSERT INTO lm_employees (sno, emp_id, name, dept, status) VALUES (%s, %s, %s, %s, 'Active')",
                lm_defaults,
            )

        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database initialized successfully.")
    except mysql.connector.Error as e:
        print(f"❌ Database initialization error: {e}")


# ═══════════════════════════════════════════════════════════════════════
# EMAIL HELPERS  (Render-fix: uses SSL/port 465 by default)
# ═══════════════════════════════════════════════════════════════════════

def send_email(to_email, subject, body_html):
    """Send an email using Gmail SMTP. Uses SSL (port 465) by default — Render
    free tier blocks outbound port 587 STARTTLS, but 465 SSL works fine."""
    import smtplib
    import ssl
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("⚠️  Gmail credentials not configured.")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = GMAIL_USER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_html, "html"))

        if SMTP_MODE == "ssl":
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as server:
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.sendmail(GMAIL_USER, to_email, msg.as_string())
        else:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.starttls()
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.sendmail(GMAIL_USER, to_email, msg.as_string())

        print(f"📧 Email sent to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Email send failed to {to_email}: {e}")
        return False


def send_otp_email(to_email, otp_code):
    subject = "REYDM – Your Verification Code"
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:30px;
                border:1px solid #e0e0e0;border-radius:12px;">
        <h2 style="color:#1a1a2e;text-align:center;">Verification Code</h2>
        <p style="color:#555;text-align:center;">Use this code to complete your registration:</p>
        <div style="text-align:center;margin:24px 0;">
            <span style="font-size:32px;font-weight:700;letter-spacing:8px;
                         color:#e94560;background:#fef2f2;padding:12px 24px;
                         border-radius:8px;">{otp_code}</span>
        </div>
        <p style="color:#888;text-align:center;font-size:13px;">
            This code expires in <strong>10 minutes</strong>.
        </p>
    </div>
    """
    return send_email(to_email, subject, body)


def send_approval_notification(to_email, full_name):
    subject = "REYDM – New User Awaiting Approval"
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:30px;
                border:1px solid #e0e0e0;border-radius:12px;">
        <h2 style="color:#1a1a2e;">New Registration Request</h2>
        <p>A new user has registered and is waiting for admin approval:</p>
        <table style="width:100%;margin:16px 0;">
            <tr><td style="color:#888;">Name:</td><td><strong>{full_name}</strong></td></tr>
            <tr><td style="color:#888;">Email:</td><td><strong>{to_email}</strong></td></tr>
        </table>
    </div>
    """
    conn = get_db()
    if conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT email FROM users WHERE role='admin' AND is_approved=1")
        admins = cur.fetchall()
        cur.close()
        conn.close()
        for admin in admins:
            send_email(admin["email"], subject, body)


def send_user_approved_email(to_email, full_name):
    subject = "REYDM – Account Approved!"
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:30px;
                border:1px solid #e0e0e0;border-radius:12px;">
        <h2 style="color:#16a34a;text-align:center;">Welcome, {full_name}!</h2>
        <p style="text-align:center;color:#555;">
            Your account has been approved. You can now log in to REYDM.
        </p>
    </div>
    """
    return send_email(to_email, subject, body)


def send_reminder_email(to_email, project_name, reminder_time):
    subject = f"⏰ Reminder: {project_name}"
    # Format IST-aware
    if hasattr(reminder_time, "strftime"):
        formatted_time = reminder_time.strftime("%B %d, %Y at %I:%M %p")
    else:
        formatted_time = str(reminder_time)
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:30px;
                border:1px solid #e0e0e0;border-radius:12px;">
        <h2 style="color:#e94560;text-align:center;">Project Reminder</h2>
        <div style="background:#fef2f2;padding:20px;border-radius:8px;margin:16px 0;">
            <h3 style="margin:0 0 8px;color:#1a1a2e;">{project_name}</h3>
            <p style="margin:0;color:#666;">Scheduled: {formatted_time} (IST)</p>
        </div>
    </div>
    """
    return send_email(to_email, subject, body)


# ═══════════════════════════════════════════════════════════════════════
# AUTH DECORATORS
# ═══════════════════════════════════════════════════════════════════════

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("chat"))
        return f(*args, **kwargs)
    return decorated


def tool_required(tool_key):
    """Decorator: ensures the user has access to the given tool."""
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in first.", "warning")
                return redirect(url_for("login"))
            if session.get("role") == "admin":
                return f(*args, **kwargs)
            allowed = session.get("allowed_tools", [])
            if tool_key not in allowed:
                flash("You don't have access to this tool.", "danger")
                return redirect(url_for("chat"))
            return f(*args, **kwargs)
        return decorated
    return wrapper


PRESET_THEMES = {
    "Sky Blue": {
        "name": "Sky Blue",
        "is_gradient": False,
        "primary": "#0284c7",
        "accent": "#38bdf8",
        "primary_hover": "#0369a1",
        "bg_light": "#f0f9ff",
        "panel_light": "rgba(255, 255, 255, 0.88)",
        "border_light": "rgba(14, 165, 233, 0.12)",
        "msg_mine_light": "#0284c7",
        "msg_theirs_light": "#ffffff",
        "bg_dark": "#030712",
        "panel_dark": "rgba(17, 24, 39, 0.85)",
        "border_dark": "rgba(14, 165, 233, 0.15)",
        "msg_mine_dark": "#0ea5e9",
        "msg_theirs_dark": "rgba(255, 255, 255, 0.05)",
        "gradient_style": ""
    },
    "Emerald Green": {
        "name": "Emerald Green",
        "is_gradient": False,
        "primary": "#059669",
        "accent": "#34d399",
        "primary_hover": "#047857",
        "bg_light": "#f0fdf4",
        "panel_light": "rgba(255, 255, 255, 0.88)",
        "border_light": "rgba(5, 150, 105, 0.1)",
        "msg_mine_light": "#059669",
        "msg_theirs_light": "#ffffff",
        "bg_dark": "#022c22",
        "panel_dark": "rgba(6, 78, 59, 0.5)",
        "border_dark": "rgba(50, 200, 150, 0.15)",
        "msg_mine_dark": "#10b981",
        "msg_theirs_dark": "rgba(255, 255, 255, 0.05)",
        "gradient_style": ""
    },
    "Royal Indigo": {
        "name": "Royal Indigo",
        "is_gradient": False,
        "primary": "#4f46e5",
        "accent": "#818cf8",
        "primary_hover": "#4338ca",
        "bg_light": "#f5f3ff",
        "panel_light": "rgba(255, 255, 255, 0.88)",
        "border_light": "rgba(79, 70, 229, 0.1)",
        "msg_mine_light": "#4f46e5",
        "msg_theirs_light": "#ffffff",
        "bg_dark": "#090514",
        "panel_dark": "rgba(15, 10, 30, 0.85)",
        "border_dark": "rgba(79, 70, 229, 0.18)",
        "msg_mine_dark": "#6366f1",
        "msg_theirs_dark": "rgba(255, 255, 255, 0.05)",
        "gradient_style": ""
    },
    "Rose Pink": {
        "name": "Rose Pink",
        "is_gradient": False,
        "primary": "#db2777",
        "accent": "#f472b6",
        "primary_hover": "#be185d",
        "bg_light": "#fff1f2",
        "panel_light": "rgba(255, 255, 255, 0.88)",
        "border_light": "rgba(219, 39, 119, 0.1)",
        "msg_mine_light": "#db2777",
        "msg_theirs_light": "#ffffff",
        "bg_dark": "#1c020d",
        "panel_dark": "rgba(30, 5, 15, 0.85)",
        "border_dark": "rgba(219, 39, 119, 0.18)",
        "msg_mine_dark": "#ec4899",
        "msg_theirs_dark": "rgba(255, 255, 255, 0.05)",
        "gradient_style": ""
    },
    "Sunset Amber": {
        "name": "Sunset Amber",
        "is_gradient": False,
        "primary": "#ea580c",
        "accent": "#fb923c",
        "primary_hover": "#ca8a04",
        "bg_light": "#fff7ed",
        "panel_light": "rgba(255, 255, 255, 0.88)",
        "border_light": "rgba(234, 88, 12, 0.1)",
        "msg_mine_light": "#ea580c",
        "msg_theirs_light": "#ffffff",
        "bg_dark": "#140500",
        "panel_dark": "rgba(25, 10, 5, 0.85)",
        "border_dark": "rgba(234, 88, 12, 0.18)",
        "msg_mine_dark": "#f97316",
        "msg_theirs_dark": "rgba(255, 255, 255, 0.05)",
        "gradient_style": ""
    },
    "Teal Breeze": {
        "name": "Teal Breeze",
        "is_gradient": False,
        "primary": "#0d9488",
        "accent": "#2dd4bf",
        "primary_hover": "#0f766e",
        "bg_light": "#f0fdfa",
        "panel_light": "rgba(255, 255, 255, 0.88)",
        "border_light": "rgba(13, 148, 136, 0.1)",
        "msg_mine_light": "#0d9488",
        "msg_theirs_light": "#ffffff",
        "bg_dark": "#022b26",
        "panel_dark": "rgba(4, 47, 43, 0.85)",
        "border_dark": "rgba(13, 148, 136, 0.18)",
        "msg_mine_dark": "#14b8a6",
        "msg_theirs_dark": "rgba(255, 255, 255, 0.05)",
        "gradient_style": ""
    },
    "Ocean Gradient": {
        "name": "Ocean Gradient",
        "is_gradient": True,
        "primary": "#0284c7",
        "accent": "#0d9488",
        "primary_hover": "#0369a1",
        "bg_light": "#f0f9ff",
        "panel_light": "rgba(255, 255, 255, 0.88)",
        "border_light": "rgba(14, 165, 233, 0.12)",
        "msg_mine_light": "linear-gradient(135deg, #0284c7, #0d9488)",
        "msg_theirs_light": "#ffffff",
        "bg_dark": "#020b14",
        "panel_dark": "rgba(17, 24, 39, 0.85)",
        "border_dark": "rgba(14, 165, 233, 0.15)",
        "msg_mine_dark": "linear-gradient(135deg, #0ea5e9, #14b8a6)",
        "msg_theirs_dark": "rgba(255, 255, 255, 0.05)",
        "gradient_style": "linear-gradient(135deg, #0284c7, #0d9488)"
    },
    "Sunset Flame": {
        "name": "Sunset Flame",
        "is_gradient": True,
        "primary": "#f97316",
        "accent": "#ec4899",
        "primary_hover": "#ea580c",
        "bg_light": "#fff5f5",
        "panel_light": "rgba(255, 255, 255, 0.88)",
        "border_light": "rgba(249, 115, 22, 0.1)",
        "msg_mine_light": "linear-gradient(135deg, #f97316, #ec4899)",
        "msg_theirs_light": "#ffffff",
        "bg_dark": "#14050a",
        "panel_dark": "rgba(30, 10, 20, 0.85)",
        "border_dark": "rgba(249, 115, 22, 0.18)",
        "msg_mine_dark": "linear-gradient(135deg, #ff7e33, #ff66b2)",
        "msg_theirs_dark": "rgba(255, 255, 255, 0.05)",
        "gradient_style": "linear-gradient(135deg, #f97316, #ec4899)"
    },
    "Purple Rain": {
        "name": "Purple Rain",
        "is_gradient": True,
        "primary": "#8b5cf6",
        "accent": "#3b82f6",
        "primary_hover": "#7c3aed",
        "bg_light": "#faf5ff",
        "panel_light": "rgba(255, 255, 255, 0.88)",
        "border_light": "rgba(139, 92, 246, 0.1)",
        "msg_mine_light": "linear-gradient(135deg, #8b5cf6, #3b82f6)",
        "msg_theirs_light": "#ffffff",
        "bg_dark": "#0a0518",
        "panel_dark": "rgba(15, 10, 30, 0.85)",
        "border_dark": "rgba(139, 92, 246, 0.18)",
        "msg_mine_dark": "linear-gradient(135deg, #a78bfa, #60a5fa)",
        "msg_theirs_dark": "rgba(255, 255, 255, 0.05)",
        "gradient_style": "linear-gradient(135deg, #8b5cf6, #3b82f6)"
    },
    "Cyberpunk": {
        "name": "Cyberpunk",
        "is_gradient": True,
        "primary": "#d946ef",
        "accent": "#f43f5e",
        "primary_hover": "#c084fc",
        "bg_light": "#fdf4ff",
        "panel_light": "rgba(255, 255, 255, 0.88)",
        "border_light": "rgba(217, 70, 239, 0.1)",
        "msg_mine_light": "linear-gradient(135deg, #d946ef, #f43f5e)",
        "msg_theirs_light": "#ffffff",
        "bg_dark": "#14001a",
        "panel_dark": "rgba(25, 5, 30, 0.85)",
        "border_dark": "rgba(217, 70, 239, 0.18)",
        "msg_mine_dark": "linear-gradient(135deg, #f472b6, #fb7185)",
        "msg_theirs_dark": "rgba(255, 255, 255, 0.05)",
        "gradient_style": "linear-gradient(135deg, #d946ef, #f43f5e)"
    },
    "Citrus Punch": {
        "name": "Citrus Punch",
        "is_gradient": True,
        "primary": "#f59e0b",
        "accent": "#ef4444",
        "primary_hover": "#d97706",
        "bg_light": "#fffbeb",
        "panel_light": "rgba(255, 255, 255, 0.88)",
        "border_light": "rgba(245, 158, 11, 0.1)",
        "msg_mine_light": "linear-gradient(135deg, #f59e0b, #ef4444)",
        "msg_theirs_light": "#ffffff",
        "bg_dark": "#1a0505",
        "panel_dark": "rgba(30, 10, 10, 0.85)",
        "border_dark": "rgba(245, 158, 11, 0.18)",
        "msg_mine_dark": "linear-gradient(135deg, #fbbf24, #f87171)",
        "msg_theirs_dark": "rgba(255, 255, 255, 0.05)",
        "gradient_style": "linear-gradient(135deg, #f59e0b, #ef4444)"
    },
    "Northern Lights": {
        "name": "Northern Lights",
        "is_gradient": True,
        "primary": "#0f766e",
        "accent": "#15803d",
        "primary_hover": "#0d9488",
        "bg_light": "#f0fdf4",
        "panel_light": "rgba(255, 255, 255, 0.88)",
        "border_light": "rgba(15, 118, 110, 0.1)",
        "msg_mine_light": "linear-gradient(135deg, #0f766e, #15803d)",
        "msg_theirs_light": "#ffffff",
        "bg_dark": "#021a0f",
        "panel_dark": "rgba(4, 40, 24, 0.85)",
        "border_dark": "rgba(15, 118, 110, 0.18)",
        "msg_mine_dark": "linear-gradient(135deg, #14b8a6, #34d399)",
        "msg_theirs_dark": "rgba(255, 255, 255, 0.05)",
        "gradient_style": "linear-gradient(135deg, #0f766e, #15803d)"
    }
}

def get_global_theme():
    try:
        conn = get_db()
        if conn:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'global_theme'")
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                return json.loads(row["setting_value"])
    except Exception as e:
        print(f"Error fetching global theme: {e}")
    return PRESET_THEMES["Sky Blue"]

def get_user_tools():
    if session.get("role") == "admin":
        return list(AVAILABLE_TOOLS.keys())
    return session.get("allowed_tools", [])


@app.context_processor
def inject_tools():
    user_tools = []
    if "user_id" in session:
        for key in get_user_tools():
            if key in AVAILABLE_TOOLS:
                user_tools.append({"key": key, **AVAILABLE_TOOLS[key]})
    return dict(
        user_tools=user_tools,
        all_tools=AVAILABLE_TOOLS,
        get_user_tools=get_user_tools,
        global_theme=get_global_theme(),
    )


# ═══════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("chat"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("chat"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        if not conn:
            flash("Database connection error.", "danger")
            return render_template("login.html")

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "danger")
            return render_template("login.html")

        if not user["is_approved"]:
            flash("Your account is awaiting admin approval.", "warning")
            return render_template("login.html")

        if not user["is_active"]:
            flash("Your account has been deactivated.", "danger")
            return render_template("login.html")

        session.permanent = True
        session["user_id"] = user["id"]
        session["full_name"] = user["full_name"]
        session["email"] = user["email"]
        session["role"] = user["role"]

        # Parse allowed_tools
        tools = user.get("allowed_tools")
        if tools:
            if isinstance(tools, str):
                try:
                    tools = json.loads(tools)
                except Exception:
                    tools = []
            session["allowed_tools"] = tools if isinstance(tools, list) else []
        else:
            session["allowed_tools"] = []

        # Update last_active
        conn2 = get_db()
        if conn2:
            c2 = conn2.cursor()
            c2.execute("UPDATE users SET last_active = %s WHERE id = %s", (now_ist(), user["id"]))
            conn2.commit()
            c2.close()
            conn2.close()

        flash(f"Welcome back, {user['full_name']}!", "success")
        return redirect(url_for("chat"))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("chat"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        errors = []
        if not full_name:
            errors.append("Full name is required.")
        if not email:
            errors.append("Email is required.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm_password:
            errors.append("Passwords do not match.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("register.html")

        conn = get_db()
        if not conn:
            flash("Database connection error.", "danger")
            return render_template("register.html")

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            flash("Email is already registered.", "danger")
            cur.close()
            conn.close()
            return render_template("register.html")

        otp_code = "".join(random.choices(string.digits, k=6))
        expires_at = now_ist() + timedelta(minutes=10)

        cur.execute(
            """INSERT INTO otp_tokens (email, otp_code, purpose, expires_at)
               VALUES (%s, %s, 'register', %s)""",
            (email, otp_code, expires_at),
        )
        conn.commit()
        cur.close()
        conn.close()

        threading.Thread(target=send_otp_email, args=(email, otp_code), daemon=True).start()

        session["reg_data"] = {
            "full_name": full_name,
            "email": email,
            "password": password,
        }

        flash("A verification code has been sent to your email.", "info")
        return redirect(url_for("verify_otp"))

    return render_template("register.html")


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    reg_data = session.get("reg_data")
    if not reg_data:
        flash("Please register first.", "warning")
        return redirect(url_for("register"))

    if request.method == "POST":
        otp_input = request.form.get("otp", "").strip()
        email = reg_data["email"]

        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT * FROM otp_tokens
               WHERE email = %s AND otp_code = %s AND purpose = 'register'
                     AND is_used = 0 AND expires_at > NOW()
               ORDER BY id DESC LIMIT 1""",
            (email, otp_input),
        )
        token = cur.fetchone()

        if not token:
            flash("Invalid or expired OTP.", "danger")
            cur.close()
            conn.close()
            return render_template("verify_otp.html", email=email)

        cur.execute("UPDATE otp_tokens SET is_used = 1 WHERE id = %s", (token["id"],))

        pw_hash = generate_password_hash(reg_data["password"])
        try:
            cur.execute(
                """INSERT INTO users (full_name, email, password_hash, role, is_approved, allowed_tools)
                   VALUES (%s, %s, %s, 'user', 0, '[]')""",
                (reg_data["full_name"], email, pw_hash),
            )
            conn.commit()
        except mysql.connector.IntegrityError:
            flash("Email already registered.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for("register"))

        cur.close()
        conn.close()

        threading.Thread(
            target=send_approval_notification,
            args=(email, reg_data["full_name"]),
            daemon=True,
        ).start()

        session.pop("reg_data", None)
        flash("Registration successful! Pending admin approval.", "success")
        return redirect(url_for("login"))

    return render_template("verify_otp.html", email=reg_data["email"])


@app.route("/resend-otp", methods=["POST"])
def resend_otp():
    reg_data = session.get("reg_data")
    if not reg_data:
        return jsonify({"success": False, "message": "Session expired."}), 400

    email = reg_data["email"]
    otp_code = "".join(random.choices(string.digits, k=6))
    expires_at = now_ist() + timedelta(minutes=10)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO otp_tokens (email, otp_code, purpose, expires_at)
           VALUES (%s, %s, 'register', %s)""",
        (email, otp_code, expires_at),
    )
    conn.commit()
    cur.close()
    conn.close()

    threading.Thread(target=send_otp_email, args=(email, otp_code), daemon=True).start()
    return jsonify({"success": True, "message": "A new OTP has been sent."})


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ═══════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════

@app.route("/dashboard")
@login_required
def dashboard():
    return redirect(url_for("chat"))


# ═══════════════════════════════════════════════════════════════════════
# REMINDERS
# ═══════════════════════════════════════════════════════════════════════

@app.route("/reminders/add", methods=["GET", "POST"])
@login_required
@tool_required("reminder")
def add_reminder():
    if request.method == "POST":
        project_name = request.form.get("project_name", "").strip()
        reminder_date = request.form.get("reminder_date", "")
        reminder_time = request.form.get("reminder_time", "")

        if not project_name or not reminder_date or not reminder_time:
            flash("All fields are required.", "danger")
            return render_template("add_reminder.html")

        try:
            reminder_dt = datetime.strptime(f"{reminder_date} {reminder_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            flash("Invalid date/time format.", "danger")
            return render_template("add_reminder.html")

        if reminder_dt <= now_ist():
            flash("Reminder must be in the future.", "danger")
            return render_template("add_reminder.html")

        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id FROM reminders WHERE project_name = %s AND reminder_datetime = %s",
            (project_name, reminder_dt),
        )
        if cur.fetchone():
            flash("Duplicate reminder exists.", "warning")
            cur.close()
            conn.close()
            return render_template("add_reminder.html")

        cur.execute(
            """INSERT INTO reminders (project_name, reminder_datetime, created_by)
               VALUES (%s, %s, %s)""",
            (project_name, reminder_dt, session["user_id"]),
        )
        conn.commit()
        cur.close()
        conn.close()

        flash("Reminder created successfully!", "success")
        return redirect(url_for("chat"))

    return render_template("add_reminder.html")


@app.route("/reminders/delete/<int:reminder_id>", methods=["POST"])
@login_required
@tool_required("reminder")
def delete_reminder(reminder_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM reminders WHERE id = %s", (reminder_id,))
    reminder = cur.fetchone()
    if not reminder:
        flash("Reminder not found.", "danger")
    elif session["role"] != "admin" and reminder["created_by"] != session["user_id"]:
        flash("You can only delete your own reminders.", "danger")
    else:
        cur.execute("DELETE FROM reminders WHERE id = %s", (reminder_id,))
        conn.commit()
        flash("Reminder deleted.", "success")
    cur.close()
    conn.close()
    return redirect(url_for("chat"))


@app.route("/reminders/edit/<int:reminder_id>", methods=["GET", "POST"])
@login_required
@tool_required("reminder")
def edit_reminder(reminder_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM reminders WHERE id = %s", (reminder_id,))
    reminder = cur.fetchone()
    if not reminder:
        flash("Reminder not found.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for("chat"))
    if session["role"] != "admin" and reminder["created_by"] != session["user_id"]:
        flash("You can only edit your own reminders.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for("chat"))

    if request.method == "POST":
        project_name = request.form.get("project_name", "").strip()
        reminder_date = request.form.get("reminder_date", "")
        reminder_time = request.form.get("reminder_time", "")
        try:
            reminder_dt = datetime.strptime(f"{reminder_date} {reminder_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            flash("Invalid date/time format.", "danger")
            return render_template("edit_reminder.html", reminder=reminder)
        cur.execute(
            "SELECT id FROM reminders WHERE project_name = %s AND reminder_datetime = %s AND id != %s",
            (project_name, reminder_dt, reminder_id),
        )
        if cur.fetchone():
            flash("Duplicate reminder exists.", "warning")
            return render_template("edit_reminder.html", reminder=reminder)
        cur.execute(
            "UPDATE reminders SET project_name = %s, reminder_datetime = %s WHERE id = %s",
            (project_name, reminder_dt, reminder_id),
        )
        conn.commit()
        flash("Reminder updated.", "success")
        cur.close()
        conn.close()
        return redirect(url_for("chat"))

    cur.close()
    conn.close()
    return render_template("edit_reminder.html", reminder=reminder)


@app.route("/reminders/trigger/<int:reminder_id>", methods=["POST"])
@login_required
def trigger_reminder(reminder_id):
    conn = get_db()
    if not conn:
        return jsonify({"success": False, "message": "Database error."}), 500
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM reminders WHERE id = %s", (reminder_id,))
    reminder = cur.fetchone()
    if not reminder:
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Not found."}), 404
    if reminder["is_sent"]:
        cur.close()
        conn.close()
        return jsonify({"success": True, "message": "Already sent."})

    cur.execute("SELECT email FROM users WHERE is_approved = 1 AND is_active = 1 AND mail_enabled = 1")
    users = cur.fetchall()
    sent_count = 0
    for user in users:
        success = send_reminder_email(user["email"], reminder["project_name"], reminder["reminder_datetime"])
        cur.execute(
            "INSERT INTO reminder_logs (reminder_id, sent_to, status) VALUES (%s, %s, %s)",
            (reminder["id"], user["email"], "sent" if success else "failed"),
        )
        if success:
            sent_count += 1

    cur.execute("UPDATE reminders SET is_sent = 1 WHERE id = %s", (reminder_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({
        "success": True,
        "message": f"Sent to {sent_count} user(s).",
        "sent_count": sent_count,
        "total_users": len(users),
    })


@app.route("/api/reminders")
@login_required
def api_reminders():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT r.*, u.full_name AS creator_name
        FROM reminders r JOIN users u ON r.created_by = u.id
        ORDER BY r.reminder_datetime ASC
    """)
    reminders = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{
        "id": r["id"], "project_name": r["project_name"],
        "reminder_datetime": r["reminder_datetime"].strftime("%Y-%m-%d %H:%M"),
        "creator_name": r["creator_name"], "is_sent": r["is_sent"],
        "created_by": r["created_by"],
    } for r in reminders])


# ═══════════════════════════════════════════════════════════════════════
# NIGHT SHIFT ATTENDANCE
# ═══════════════════════════════════════════════════════════════════════

@app.route("/nightshift")
@login_required
@tool_required("nightshift")
def nightshift():
    return render_template("nightshift.html")


@app.route("/api/ns/employees")
@login_required
@tool_required("nightshift")
def api_ns_employees():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM ns_employees ORDER BY emp_id ASC")
    emps = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(emps)


@app.route("/api/ns/employees", methods=["POST"])
@login_required
@tool_required("nightshift")
def api_ns_add_employee():
    data = request.get_json() or {}
    emp_id = str(data.get("emp_id", "")).strip()
    name = str(data.get("name", "")).strip()
    dept = str(data.get("dept", "")).strip()
    status = data.get("status", "active")
    if status not in ("active", "resigned"):
        status = "active"
    if not emp_id or not name:
        return jsonify({"success": False, "message": "ID and Name required."}), 400

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO ns_employees (emp_id, name, dept, status) VALUES (%s, %s, %s, %s)",
            (emp_id, name, dept, status),
        )
        conn.commit()
    except mysql.connector.IntegrityError:
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Employee ID already exists."}), 400
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/ns/employees/<emp_id>", methods=["PUT"])
@login_required
@tool_required("nightshift")
def api_ns_update_employee(emp_id):
    data = request.get_json() or {}
    new_id = str(data.get("emp_id", "")).strip()
    name = str(data.get("name", "")).strip()
    dept = str(data.get("dept", "")).strip()
    status = data.get("status", "active")
    if status not in ("active", "resigned"):
        status = "active"
    if not new_id or not name:
        return jsonify({"success": False, "message": "ID and Name required."}), 400

    conn = get_db()
    cur = conn.cursor()
    if new_id != emp_id:
        cur.execute("UPDATE ns_attendance SET emp_id = %s WHERE emp_id = %s", (new_id, emp_id))
    cur.execute(
        "UPDATE ns_employees SET emp_id = %s, name = %s, dept = %s, status = %s WHERE emp_id = %s",
        (new_id, name, dept, status, emp_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/ns/employees/<emp_id>", methods=["DELETE"])
@login_required
@tool_required("nightshift")
def api_ns_delete_employee(emp_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM ns_attendance WHERE emp_id = %s", (emp_id,))
    cur.execute("DELETE FROM ns_employees WHERE emp_id = %s", (emp_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/ns/employees/bulk", methods=["POST"])
@login_required
@tool_required("nightshift")
def api_ns_bulk_add():
    data = request.get_json() or {}
    employees = data.get("employees", [])
    added = skipped = 0
    conn = get_db()
    cur = conn.cursor()
    for emp in employees:
        try:
            cur.execute(
                "INSERT INTO ns_employees (emp_id, name, dept, status) VALUES (%s, %s, %s, %s)",
                (emp.get("emp_id"), emp.get("name"), emp.get("dept", ""), emp.get("status", "active")),
            )
            added += 1
        except mysql.connector.IntegrityError:
            skipped += 1
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True, "added": added, "skipped": skipped})


@app.route("/api/ns/attendance/<int:year>/<int:month>")
@login_required
@tool_required("nightshift")
def api_ns_attendance(year, month):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT emp_id, DAY(att_date) AS day_num
           FROM ns_attendance
           WHERE YEAR(att_date) = %s AND MONTH(att_date) = %s AND present = 1""",
        (year, month),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = {}
    for r in rows:
        result.setdefault(r["emp_id"], []).append(r["day_num"])
    return jsonify(result)


@app.route("/api/ns/attendance/toggle", methods=["POST"])
@login_required
@tool_required("nightshift")
def api_ns_toggle_attendance():
    data = request.get_json() or {}
    emp_id = data["emp_id"]
    year = int(data["year"])
    month = int(data["month"])
    day = int(data["day"])
    att_date = f"{year}-{month:02d}-{day:02d}"

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM ns_attendance WHERE emp_id = %s AND att_date = %s", (emp_id, att_date))
    existing = cur.fetchone()
    if existing:
        cur.execute("DELETE FROM ns_attendance WHERE id = %s", (existing["id"],))
        present = False
    else:
        cur.execute("INSERT INTO ns_attendance (emp_id, att_date) VALUES (%s, %s)", (emp_id, att_date))
        present = True
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True, "present": present})


@app.route("/api/ns/attendance/year/<int:year>")
@login_required
@tool_required("nightshift")
def api_ns_year_attendance(year):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT emp_id, MONTH(att_date) AS month_num, COUNT(*) AS total
           FROM ns_attendance
           WHERE YEAR(att_date) = %s AND present = 1
           GROUP BY emp_id, MONTH(att_date)""",
        (year,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = {}
    for r in rows:
        result.setdefault(r["emp_id"], {})[r["month_num"]] = r["total"]
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════════
# SIMPLE TOOL PAGES
# ═══════════════════════════════════════════════════════════════════════

@app.route("/charpalette")
@login_required
@tool_required("charpalette")
def charpalette():
    return render_template("charpalette.html")


@app.route("/costconverter")
@login_required
@tool_required("costconverter")
def costconverter():
    return render_template("costconverter.html")


@app.route("/projectanalysis")
@login_required
@tool_required("projectanalysis")
def projectanalysis():
    return render_template("projectanalysis.html")


@app.route("/pdfunlocker")
@login_required
@tool_required("pdfunlocker")
def pdfunlocker():
    return render_template("pdfunlocker.html")


# ═══════════════════════════════════════════════════════════════════════
# ATTENDANCE (Login/Logout Tracker) — IST + idempotent upsert logic
# ═══════════════════════════════════════════════════════════════════════

@app.route("/attendance")
@login_required
@tool_required("attendance")
def attendance():
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    # Active session today (no logout yet)
    cur.execute(
        """SELECT * FROM attendance_logs
           WHERE user_id = %s AND login_date = CURDATE() AND logout_time IS NULL
           ORDER BY login_time DESC LIMIT 1""",
        (session["user_id"],),
    )
    active_session = cur.fetchone()

    # Today's completed log (if any)
    cur.execute(
        """SELECT * FROM attendance_logs
           WHERE user_id = %s AND login_date = CURDATE()
           ORDER BY login_time DESC LIMIT 1""",
        (session["user_id"],),
    )
    today_log = cur.fetchone()

    cur.execute(
        """SELECT * FROM attendance_logs
           WHERE user_id = %s AND login_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
           ORDER BY login_date DESC, login_time DESC""",
        (session["user_id"],),
    )
    recent_logs = cur.fetchall()

    cur.execute(
        "SELECT COUNT(*) AS cnt FROM attendance_requests WHERE user_id = %s AND status = 'pending'",
        (session["user_id"],),
    )
    pending_requests = cur.fetchone()["cnt"]

    cur.execute(
        """SELECT * FROM attendance_requests
           WHERE user_id = %s ORDER BY created_at DESC LIMIT 20""",
        (session["user_id"],),
    )
    my_requests = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "attendance.html",
        active_session=active_session,
        today_log=today_log,
        recent_logs=recent_logs,
        pending_requests=pending_requests,
        my_requests=my_requests,
    )


@app.route("/attendance/login", methods=["POST"])
@login_required
@tool_required("attendance")
def attendance_login():
    """
    Idempotent login:
      - If a row for (user, today) already exists with login_time → reject (use upsert logic).
      - Otherwise insert a new row with login_time.
    """
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    today = today_ist()
    now = now_ist()

    cur.execute(
        "SELECT * FROM attendance_logs WHERE user_id = %s AND login_date = %s",
        (session["user_id"], today),
    )
    existing = cur.fetchone()

    if existing:
        if existing["logout_time"] is None:
            flash("You are already logged in for today. Please logout first.", "warning")
        else:
            flash("You have already completed today's attendance. New login not allowed.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for("attendance"))

    cur.execute(
        """INSERT INTO attendance_logs (user_id, login_date, login_time)
           VALUES (%s, %s, %s)""",
        (session["user_id"], today, now),
    )
    conn.commit()
    cur.close()
    conn.close()
    flash(f"Logged in at {now.strftime('%I:%M %p')} (IST)", "success")
    return redirect(url_for("attendance"))


@app.route("/attendance/logout", methods=["POST"])
@login_required
@tool_required("attendance")
def attendance_logout():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT * FROM attendance_logs
           WHERE user_id = %s AND login_date = CURDATE() AND logout_time IS NULL
           ORDER BY login_time DESC LIMIT 1""",
        (session["user_id"],),
    )
    active = cur.fetchone()
    if not active:
        flash("No active login session found for today.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for("attendance"))

    now = now_ist()
    login_time = active["login_time"]
    diff = (now - login_time).total_seconds() / 3600.0
    hours_spent = round(diff, 2)

    cur.execute(
        "UPDATE attendance_logs SET logout_time = %s, hours_spent = %s WHERE id = %s",
        (now, hours_spent, active["id"]),
    )
    conn.commit()
    cur.close()
    conn.close()
    flash(f"Logged out at {now.strftime('%I:%M %p')} (IST). Hours: {hours_spent} hrs", "success")
    return redirect(url_for("attendance"))


@app.route("/attendance/request", methods=["POST"])
@login_required
@tool_required("attendance")
def attendance_request():
    """User submits a request to manually add/change attendance.
    Smart logic:
      - If user requests a date that already has a login but no logout,
        treat the request as a logout-only update (no new row creation).
      - If date has full row (login + logout), reject as duplicate.
      - If no row exists, request creates a new entry on approval.
    """
    req_date_str = request.form.get("request_date", "")
    req_login = request.form.get("request_login", "")
    req_logout = request.form.get("request_logout", "")
    reason = request.form.get("reason", "").strip()

    if not req_date_str or not req_logout:
        flash("Date and logout time are required.", "danger")
        return redirect(url_for("attendance"))

    try:
        req_date = datetime.strptime(req_date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date format.", "danger")
        return redirect(url_for("attendance"))

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    # Check existing attendance for that date
    cur.execute(
        "SELECT * FROM attendance_logs WHERE user_id = %s AND login_date = %s",
        (session["user_id"], req_date),
    )
    existing = cur.fetchone()

    try:
        if existing:
            # Login already exists. Don't create a new entry — request a logout update.
            if existing["logout_time"] is not None:
                flash("This date already has full login/logout records. Request not needed.", "warning")
                cur.close()
                conn.close()
                return redirect(url_for("attendance"))

            # Existing login but no logout → user must supply only the logout time
            login_dt = existing["login_time"]
            logout_dt = datetime.strptime(f"{req_date_str} {req_logout}", "%Y-%m-%d %H:%M")
            if logout_dt <= login_dt:
                logout_dt += timedelta(days=1)

            cur.execute(
                """INSERT INTO attendance_requests
                   (user_id, request_date, requested_login, requested_logout, reason)
                   VALUES (%s, %s, %s, %s, %s)""",
                (session["user_id"], req_date, login_dt, logout_dt,
                 f"[Logout only] {reason}"),
            )
            flash("Logout-time request submitted (existing login will be reused).", "success")
        else:
            # No record — need both login and logout
            if not req_login:
                flash("This date has no login record. Please provide login time too.", "danger")
                cur.close()
                conn.close()
                return redirect(url_for("attendance"))
            login_dt = datetime.strptime(f"{req_date_str} {req_login}", "%Y-%m-%d %H:%M")
            logout_dt = datetime.strptime(f"{req_date_str} {req_logout}", "%Y-%m-%d %H:%M")
            if logout_dt <= login_dt:
                logout_dt += timedelta(days=1)

            cur.execute(
                """INSERT INTO attendance_requests
                   (user_id, request_date, requested_login, requested_logout, reason)
                   VALUES (%s, %s, %s, %s, %s)""",
                (session["user_id"], req_date, login_dt, logout_dt, reason),
            )
            flash("Attendance request submitted for admin approval.", "success")
        conn.commit()
    except ValueError:
        flash("Invalid time format.", "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("attendance"))


@app.route("/admin/attendance-requests")
@admin_required
def admin_attendance_requests():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT ar.*, u.full_name, u.email
           FROM attendance_requests ar
           JOIN users u ON ar.user_id = u.id
           ORDER BY
             CASE ar.status WHEN 'pending' THEN 0 ELSE 1 END,
             ar.created_at DESC
           LIMIT 100"""
    )
    requests_list = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("admin_attendance_requests.html", requests=requests_list)


@app.route("/admin/attendance-requests/<int:req_id>/<action>", methods=["POST"])
@admin_required
def handle_attendance_request(req_id, action):
    if action not in ("approve", "decline"):
        flash("Invalid action.", "danger")
        return redirect(url_for("admin_attendance_requests"))

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM attendance_requests WHERE id = %s", (req_id,))
    req = cur.fetchone()
    if not req:
        flash("Request not found.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for("admin_attendance_requests"))

    if action == "approve":
        login_dt = req["requested_login"]
        logout_dt = req["requested_logout"]
        diff = (logout_dt - login_dt).total_seconds() / 3600.0
        hours_spent = round(diff, 2)

        # Upsert: don't create duplicate; reuse if user already has a row for that date
        cur.execute(
            "SELECT * FROM attendance_logs WHERE user_id = %s AND login_date = %s",
            (req["user_id"], req["request_date"]),
        )
        existing = cur.fetchone()
        if existing:
            # Update only logout if login already present, otherwise overwrite
            if existing["logout_time"] is None:
                # Existing has login only — just update logout
                lt = existing["login_time"]
                new_hrs = round((logout_dt - lt).total_seconds() / 3600.0, 2)
                cur.execute(
                    "UPDATE attendance_logs SET logout_time = %s, hours_spent = %s WHERE id = %s",
                    (logout_dt, new_hrs, existing["id"]),
                )
            else:
                cur.execute(
                    """UPDATE attendance_logs
                       SET login_time = %s, logout_time = %s, hours_spent = %s
                       WHERE id = %s""",
                    (login_dt, logout_dt, hours_spent, existing["id"]),
                )
        else:
            cur.execute(
                """INSERT INTO attendance_logs (user_id, login_date, login_time, logout_time, hours_spent)
                   VALUES (%s, %s, %s, %s, %s)""",
                (req["user_id"], req["request_date"], login_dt, logout_dt, hours_spent),
            )

        cur.execute(
            "UPDATE attendance_requests SET status = 'approved', reviewed_by = %s WHERE id = %s",
            (session["user_id"], req_id),
        )
        flash("Request approved and attendance logged.", "success")
    else:
        cur.execute(
            "UPDATE attendance_requests SET status = 'declined', reviewed_by = %s WHERE id = %s",
            (session["user_id"], req_id),
        )
        flash("Request declined.", "info")

    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("admin_attendance_requests"))


@app.route("/api/attendance/chart")
@login_required
def api_attendance_chart():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT login_date, SUM(hours_spent) AS total_hours
           FROM attendance_logs
           WHERE user_id = %s AND login_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
             AND hours_spent IS NOT NULL
           GROUP BY login_date ORDER BY login_date ASC""",
        (session["user_id"],),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([
        {"date": r["login_date"].strftime("%Y-%m-%d"), "hours": float(r["total_hours"])}
        for r in rows
    ])


# ═══════════════════════════════════════════════════════════════════════
# ADMIN: USER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

@app.route("/admin/users")
@admin_required
def admin_users():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users ORDER BY created_at DESC")
    users = cur.fetchall()
    cur.close()
    conn.close()
    for u in users:
        tools = u.get("allowed_tools")
        if tools:
            if isinstance(tools, str):
                try:
                    u["allowed_tools"] = json.loads(tools)
                except Exception:
                    u["allowed_tools"] = []
        else:
            u["allowed_tools"] = []
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/approve/<int:user_id>", methods=["POST"])
@admin_required
def approve_user(user_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if user:
        cur.execute("UPDATE users SET is_approved = 1 WHERE id = %s", (user_id,))
        conn.commit()
        threading.Thread(
            target=send_user_approved_email,
            args=(user["email"], user["full_name"]),
            daemon=True,
        ).start()
        flash(f"User {user['full_name']} approved.", "success")
    cur.close()
    conn.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/reject/<int:user_id>", methods=["POST"])
@admin_required
def reject_user(user_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if user and user["role"] != "admin":
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        flash(f"User {user['full_name']} rejected.", "info")
    cur.close()
    conn.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/toggle-active/<int:user_id>", methods=["POST"])
@admin_required
def toggle_user_active(user_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if user and user["id"] != session["user_id"]:
        new_status = 0 if user["is_active"] else 1
        cur.execute("UPDATE users SET is_active = %s WHERE id = %s", (new_status, user_id))
        conn.commit()
        flash(f"User {user['full_name']} {'activated' if new_status else 'deactivated'}.", "success")
    cur.close()
    conn.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/toggle-mail/<int:user_id>", methods=["POST"])
@admin_required
def toggle_mail(user_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if user:
        new_status = 0 if user["mail_enabled"] else 1
        cur.execute("UPDATE users SET mail_enabled = %s WHERE id = %s", (new_status, user_id))
        conn.commit()
        flash(f"Email {'enabled' if new_status else 'disabled'} for {user['full_name']}.", "success")
    cur.close()
    conn.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/change-role/<int:user_id>", methods=["POST"])
@admin_required
def change_role(user_id):
    new_role = request.form.get("role", "user")
    if new_role not in ("admin", "user"):
        flash("Invalid role.", "danger")
        return redirect(url_for("admin_users"))
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if user and user["id"] != session["user_id"]:
        cur.execute("UPDATE users SET role = %s WHERE id = %s", (new_role, user_id))
        conn.commit()
        flash(f"Role for {user['full_name']} changed to {new_role}.", "success")
    cur.close()
    conn.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/reset-password/<int:user_id>", methods=["POST"])
@admin_required
def reset_password(user_id):
    new_password = request.form.get("new_password", "")
    if len(new_password) < 6:
        flash("Password must be at least 6 characters.", "danger")
        return redirect(url_for("admin_users"))
    conn = get_db()
    cur = conn.cursor()
    pw_hash = generate_password_hash(new_password)
    cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (pw_hash, user_id))
    conn.commit()
    cur.close()
    conn.close()
    flash("Password reset successfully.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/toggle-tool/<int:user_id>/<tool_key>", methods=["POST"])
@admin_required
def toggle_tool(user_id, tool_key):
    if tool_key not in AVAILABLE_TOOLS:
        flash("Invalid tool.", "danger")
        return redirect(url_for("admin_users"))
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT allowed_tools FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for("admin_users"))
    tools = row.get("allowed_tools")
    if tools:
        if isinstance(tools, str):
            try:
                tools = json.loads(tools)
            except Exception:
                tools = []
    else:
        tools = []
    if not isinstance(tools, list):
        tools = []

    if tool_key in tools:
        tools.remove(tool_key)
        action = "disabled"
    else:
        tools.append(tool_key)
        action = "enabled"

    cur.execute("UPDATE users SET allowed_tools = %s WHERE id = %s", (json.dumps(tools), user_id))
    conn.commit()
    cur.close()
    conn.close()
    flash(f"{AVAILABLE_TOOLS[tool_key]['name']} {action} for user.", "success")
    return redirect(url_for("admin_users"))


# ─── ADMIN: USER DELETION API ───────────────────────────────────────

@app.route("/api/admin/users/<int:user_id>/check-messages", methods=["GET"])
@admin_required
def admin_check_user_messages(user_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, full_name, role FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404
            
        cur.execute("SELECT COUNT(*) as cnt FROM messages WHERE sender_id = %s", (user_id,))
        count = cur.fetchone()["cnt"]
        return jsonify({"success": True, "message_count": count, "full_name": user["full_name"]})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, full_name, role FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404
            
        if user["id"] == session.get("user_id"):
            return jsonify({"success": False, "message": "You cannot delete yourself!"}), 400
        if user["role"] == "admin":
            return jsonify({"success": False, "message": "Administrators cannot be deleted!"}), 400
            
        # 1. Delete user-specific file storage folder on disk
        import shutil
        username = secure_filename(user["full_name"])
        user_dir = os.path.join(UPLOAD_FOLDER, username)
        if os.path.exists(user_dir):
            try:
                shutil.rmtree(user_dir)
            except Exception as e:
                print(f"Failed to delete disk storage for user {username}: {e}")
                
        # 2. Clean up associated database entries
        cur.execute("DELETE FROM message_reactions WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM message_reactions WHERE message_id IN (SELECT id FROM messages WHERE sender_id = %s)", (user_id,))
        cur.execute("DELETE FROM message_read_receipts WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM message_read_receipts WHERE message_id IN (SELECT id FROM messages WHERE sender_id = %s)", (user_id,))
        cur.execute("DELETE FROM chat_group_members WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM pinned_conversations WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM user_conversation_cleared WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM otp_tokens WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM reminders WHERE created_by = %s", (user_id,))
        cur.execute("DELETE FROM messages WHERE sender_id = %s", (user_id,))
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        
        conn.commit()
        return jsonify({"success": True, "message": "User and all associated data deleted successfully!"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# USER PROFILE
# ═══════════════════════════════════════════════════════════════════════

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        if len(new_password) < 6:
            flash("New password must be at least 6 characters.", "danger")
        elif new_password != confirm_password:
            flash("New passwords do not match.", "danger")
        else:
            pw_hash = generate_password_hash(new_password)
            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (pw_hash, session["user_id"]))
            conn.commit()
            flash("Password updated successfully.", "success")
        cur.close()
        conn.close()

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE id = %s", (session["user_id"],))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return render_template("profile.html", user=user)


# ═══════════════════════════════════════════════════════════════════════
# REMINDER SCHEDULER (Background Thread)
# ═══════════════════════════════════════════════════════════════════════

def reminder_scheduler():
    while True:
        try:
            conn = get_db()
            if conn:
                cur = conn.cursor(dictionary=True)
                cur.execute("""
                    SELECT * FROM reminders
                    WHERE is_sent = 0
                      AND reminder_datetime <= DATE_ADD(NOW(), INTERVAL 60 SECOND)
                      AND reminder_datetime >= DATE_SUB(NOW(), INTERVAL 5 MINUTE)
                """)
                due = cur.fetchall()
                for reminder in due:
                    cur.execute(
                        "SELECT email FROM users WHERE is_approved = 1 AND is_active = 1 AND mail_enabled = 1"
                    )
                    users = cur.fetchall()
                    for user in users:
                        success = send_reminder_email(
                            user["email"], reminder["project_name"], reminder["reminder_datetime"],
                        )
                        cur.execute(
                            "INSERT INTO reminder_logs (reminder_id, sent_to, status) VALUES (%s, %s, %s)",
                            (reminder["id"], user["email"], "sent" if success else "failed"),
                        )
                    cur.execute("UPDATE reminders SET is_sent = 1 WHERE id = %s", (reminder["id"],))
                    conn.commit()
                cur.close()
                conn.close()
        except Exception as e:
            print(f"Scheduler error: {e}")
        time.sleep(30)


# ═══════════════════════════════════════════════════════════════════════
# PETTY CASH (CBE + DGL) — DB-backed
# ═══════════════════════════════════════════════════════════════════════

@app.route("/petty-cash/coimbatore")
@login_required
@tool_required("pettycash_cbe")
def pettycash_cbe():
    return render_template("petty_cash_coimbatore.html")


@app.route("/petty-cash/dindigul")
@login_required
@tool_required("pettycash_dgl")
def pettycash_dgl():
    return render_template("petty_cash_dindigul.html")


def _pc_office_check(office_key):
    """Map tool key → office shortcode."""
    return {"pettycash_cbe": "cbe", "pettycash_dgl": "dgl"}.get(office_key)


def _pc_required(office_key):
    """Return office shortcode if user has access, else None."""
    if session.get("role") == "admin":
        return _pc_office_check(office_key)
    if office_key in session.get("allowed_tools", []):
        return _pc_office_check(office_key)
    return None


@app.route("/api/pettycash/<office_key>")
@login_required
def api_pc_list(office_key):
    """Get all entries for an office. office_key = pettycash_cbe or pettycash_dgl."""
    office = _pc_required(office_key)
    if not office:
        return jsonify({"success": False, "message": "Access denied"}), 403
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT id, entry_date, particular, amount, entry_type, category
           FROM petty_cash WHERE office = %s ORDER BY entry_date ASC, id ASC""",
        (office,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{
        "id": r["id"],
        "date": r["entry_date"].strftime("%Y-%m-%d"),
        "particular": r["particular"],
        "amount": float(r["amount"]),
        "type": r["entry_type"],
        "category": r["category"] or "",
    } for r in rows])


@app.route("/api/pettycash/<office_key>", methods=["POST"])
@login_required
def api_pc_add(office_key):
    office = _pc_required(office_key)
    if not office:
        return jsonify({"success": False, "message": "Access denied"}), 403
    data = request.get_json() or {}
    try:
        d = datetime.strptime(data.get("date", ""), "%Y-%m-%d").date()
        amount = float(data.get("amount", 0))
        if amount <= 0:
            return jsonify({"success": False, "message": "Amount must be positive"}), 400
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid date or amount"}), 400

    particular = str(data.get("particular", "")).strip()[:500]
    entry_type = data.get("type", "debit")
    category = str(data.get("category", "")).strip()[:80]
    if entry_type not in ("credit", "debit"):
        entry_type = "debit"
    if not particular:
        return jsonify({"success": False, "message": "Particular required"}), 400

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """INSERT INTO petty_cash (office, entry_date, particular, amount, entry_type, category, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (office, d, particular, amount, entry_type, category, session["user_id"]),
    )
    new_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True, "id": new_id})


@app.route("/api/pettycash/<office_key>/<int:entry_id>", methods=["DELETE"])
@login_required
def api_pc_delete(office_key, entry_id):
    office = _pc_required(office_key)
    if not office:
        return jsonify({"success": False, "message": "Access denied"}), 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM petty_cash WHERE id = %s AND office = %s", (entry_id, office))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/pettycash/<office_key>/clear", methods=["POST"])
@login_required
def api_pc_clear(office_key):
    office = _pc_required(office_key)
    if not office:
        return jsonify({"success": False, "message": "Access denied"}), 403
    # Only admins can clear all
    if session.get("role") != "admin":
        return jsonify({"success": False, "message": "Admin only"}), 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM petty_cash WHERE office = %s", (office,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════════════════════════
# LEAVE MANAGER — DB-backed
# ═══════════════════════════════════════════════════════════════════════

@app.route("/leave-manager")
@login_required
@tool_required("leavemanager")
def leavemanager():
    return render_template("RDM_Leave_Manager.html")


@app.route("/api/lm/employees")
@login_required
@tool_required("leavemanager")
def api_lm_employees():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM lm_employees ORDER BY sno ASC, id ASC")
    emps = cur.fetchall()
    cur.close()
    conn.close()
    # Normalize keys to JS-friendly format
    return jsonify([{
        "sno": e["sno"],
        "empId": e["emp_id"],
        "name": e["name"],
        "dept": e["dept"] or "",
        "status": e["status"] or "Active",
        "joinDate": e["join_date"].strftime("%Y-%m-%d") if e["join_date"] else "",
        "extraCL": float(e["extra_cl"] or 0),
        "extraSL": float(e["extra_sl"] or 0),
        "extraNote": e["extra_note"] or "",
    } for e in emps])


@app.route("/api/lm/employees", methods=["POST"])
@login_required
@tool_required("leavemanager")
def api_lm_add_employee():
    data = request.get_json() or {}
    emp_id = str(data.get("empId", "")).strip().upper()
    name = str(data.get("name", "")).strip().upper()
    dept = str(data.get("dept", "")).strip()
    status = data.get("status", "Active")
    if status not in ("Active", "Inactive"):
        status = "Active"
    join_date = data.get("joinDate") or None
    try:
        join_date = datetime.strptime(join_date, "%Y-%m-%d").date() if join_date else None
    except Exception:
        join_date = None
    extra_cl = float(data.get("extraCL", 0) or 0)
    extra_sl = float(data.get("extraSL", 0) or 0)
    extra_note = str(data.get("extraNote", "")).strip()[:255]

    if not emp_id or not name or not dept:
        return jsonify({"success": False, "message": "Name, ID, Department required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT IFNULL(MAX(sno), 0) FROM lm_employees")
    next_sno = (cur.fetchone()[0] or 0) + 1
    try:
        cur.execute(
            """INSERT INTO lm_employees (sno, emp_id, name, dept, status, join_date, extra_cl, extra_sl, extra_note)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (next_sno, emp_id, name, dept, status, join_date, extra_cl, extra_sl, extra_note),
        )
        conn.commit()
    except mysql.connector.IntegrityError:
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Employee ID already exists"}), 400
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/lm/employees/<emp_id>", methods=["PUT"])
@login_required
@tool_required("leavemanager")
def api_lm_update_employee(emp_id):
    data = request.get_json() or {}
    new_id = str(data.get("empId", "")).strip().upper()
    name = str(data.get("name", "")).strip().upper()
    dept = str(data.get("dept", "")).strip()
    status = data.get("status", "Active")
    if status not in ("Active", "Inactive"):
        status = "Active"
    join_date = data.get("joinDate") or None
    try:
        join_date = datetime.strptime(join_date, "%Y-%m-%d").date() if join_date else None
    except Exception:
        join_date = None
    extra_cl = float(data.get("extraCL", 0) or 0)
    extra_sl = float(data.get("extraSL", 0) or 0)
    extra_note = str(data.get("extraNote", "")).strip()[:255]

    if not new_id or not name or not dept:
        return jsonify({"success": False, "message": "Name, ID, Department required"}), 400

    conn = get_db()
    cur = conn.cursor()
    if new_id != emp_id:
        cur.execute("UPDATE lm_leaves SET emp_id = %s WHERE emp_id = %s", (new_id, emp_id))
    try:
        cur.execute(
            """UPDATE lm_employees
               SET emp_id = %s, name = %s, dept = %s, status = %s,
                   join_date = %s, extra_cl = %s, extra_sl = %s, extra_note = %s
               WHERE emp_id = %s""",
            (new_id, name, dept, status, join_date, extra_cl, extra_sl, extra_note, emp_id),
        )
        conn.commit()
    except mysql.connector.IntegrityError:
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Employee ID conflict"}), 400
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/lm/employees/<emp_id>", methods=["DELETE"])
@login_required
@tool_required("leavemanager")
def api_lm_delete_employee(emp_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM lm_leaves WHERE emp_id = %s", (emp_id,))
    cur.execute("DELETE FROM lm_employees WHERE emp_id = %s", (emp_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/lm/leaves/<int:year>")
@login_required
@tool_required("leavemanager")
def api_lm_leaves(year):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT emp_id, mon, dy, lv_type FROM lm_leaves WHERE yr = %s", (year,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    # Format: { empId: { month: { day: type } } }
    result = {}
    for r in rows:
        result.setdefault(r["emp_id"], {}).setdefault(r["mon"], {})[str(r["dy"])] = r["lv_type"]
    return jsonify(result)


@app.route("/api/lm/leaves", methods=["POST"])
@login_required
@tool_required("leavemanager")
def api_lm_set_leave():
    data = request.get_json() or {}
    emp_id = str(data.get("empId", "")).strip().upper()
    yr = int(data.get("year", 0))
    mon = str(data.get("month", "")).strip()
    dy = int(data.get("day", 0))
    lv_type = str(data.get("type", "")).strip().upper()

    valid_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    valid_types = ['C', 'S', 'L', 'HC', 'HS', 'CH', 'SH']
    if not emp_id or yr < 2000 or mon not in valid_months or dy < 1 or dy > 31:
        return jsonify({"success": False, "message": "Invalid data"}), 400

    conn = get_db()
    cur = conn.cursor()
    if lv_type == "":
        cur.execute(
            "DELETE FROM lm_leaves WHERE emp_id = %s AND yr = %s AND mon = %s AND dy = %s",
            (emp_id, yr, mon, dy),
        )
    elif lv_type in valid_types:
        cur.execute(
            """INSERT INTO lm_leaves (emp_id, yr, mon, dy, lv_type) VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE lv_type = VALUES(lv_type)""",
            (emp_id, yr, mon, dy, lv_type),
        )
    else:
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Invalid leave type"}), 400
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/lm/leaves/bulk", methods=["POST"])
@login_required
@tool_required("leavemanager")
def api_lm_bulk_leaves():
    """Bulk import leaves. Body: { leaves: [{empId, year, month, day, type}, ...] }"""
    data = request.get_json() or {}
    leaves = data.get("leaves", [])
    valid_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    valid_types = ['C', 'S', 'L', 'HC', 'HS', 'CH', 'SH']
    added = skipped = 0
    conn = get_db()
    cur = conn.cursor()
    for lv in leaves:
        try:
            emp_id = str(lv.get("empId", "")).strip().upper()
            yr = int(lv.get("year", 0))
            mon = str(lv.get("month", "")).strip()
            dy = int(lv.get("day", 0))
            lv_type = str(lv.get("type", "")).strip().upper()
            if not emp_id or mon not in valid_months or dy < 1 or dy > 31 or lv_type not in valid_types:
                skipped += 1
                continue
            cur.execute(
                """INSERT INTO lm_leaves (emp_id, yr, mon, dy, lv_type) VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE lv_type = VALUES(lv_type)""",
                (emp_id, yr, mon, dy, lv_type),
            )
            added += 1
        except Exception:
            skipped += 1
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True, "added": added, "skipped": skipped})


@app.route("/api/lm/employees/bulk", methods=["POST"])
@login_required
@tool_required("leavemanager")
def api_lm_bulk_employees():
    data = request.get_json() or {}
    employees = data.get("employees", [])
    added = skipped = 0
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT IFNULL(MAX(sno), 0) FROM lm_employees")
    next_sno = (cur.fetchone()[0] or 0) + 1
    for emp in employees:
        emp_id = str(emp.get("empId", "")).strip().upper()
        name = str(emp.get("name", "")).strip().upper()
        dept = str(emp.get("dept", "QC")).strip()
        if not emp_id or not name:
            skipped += 1
            continue
        try:
            cur.execute(
                """INSERT INTO lm_employees (sno, emp_id, name, dept, status)
                   VALUES (%s, %s, %s, %s, 'Active')""",
                (next_sno, emp_id, name, dept),
            )
            next_sno += 1
            added += 1
        except mysql.connector.IntegrityError:
            skipped += 1
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True, "added": added, "skipped": skipped})


@app.route("/api/lm/clear-year/<int:year>", methods=["POST"])
@login_required
@tool_required("leavemanager")
def api_lm_clear_year(year):
    if session.get("role") != "admin":
        return jsonify({"success": False, "message": "Admin only"}), 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM lm_leaves WHERE yr = %s", (year,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════════════════════════
# ADMIN: SETTINGS, DB STATS, CACHE CLEAR
# ═══════════════════════════════════════════════════════════════════════

@app.route("/admin/settings")
@admin_required
def admin_settings():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    # Get DB storage details for display
    try:
        cur.execute(
            """SELECT table_name AS tn,
                      ROUND((data_length + index_length)/1024/1024, 3) AS size_mb,
                      table_rows AS rows
               FROM information_schema.tables
               WHERE table_schema = %s
               ORDER BY (data_length + index_length) DESC""",
            (DB_CONFIG["database"],),
        )
        tables = cur.fetchall()
        total_size = sum(float(t["size_mb"] or 0) for t in tables)
    except Exception:
        tables = []
        total_size = 0
    cur.close()
    conn.close()
    return render_template(
        "admin_settings.html",
        tables=tables,
        total_size=round(total_size, 2),
        db_name=DB_CONFIG["database"],
        smtp_user=GMAIL_USER,
        smtp_mode=SMTP_MODE,
    )


@app.route("/admin/cache/clear-otp", methods=["POST"])
@admin_required
def admin_clear_otp_cache():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM otp_tokens WHERE is_used = 1 OR expires_at < NOW()")
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    flash(f"Cleared {deleted} expired/used OTP tokens.", "success")
    return redirect(url_for("admin_settings"))


@app.route("/admin/cache/clear-reminder-logs", methods=["POST"])
@admin_required
def admin_clear_reminder_logs():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM reminder_logs WHERE sent_at < DATE_SUB(NOW(), INTERVAL 90 DAY)")
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    flash(f"Cleared {deleted} reminder log entries older than 90 days.", "success")
    return redirect(url_for("admin_settings"))


@app.route("/admin/cache/clear-old-attendance", methods=["POST"])
@admin_required
def admin_clear_old_attendance():
    """Clear attendance logs older than 1 year (keeps recent year)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM attendance_logs WHERE login_date < DATE_SUB(CURDATE(), INTERVAL 1 YEAR)")
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    flash(f"Cleared {deleted} attendance entries older than 1 year.", "success")
    return redirect(url_for("admin_settings"))


@app.route("/admin/cache/optimize-tables", methods=["POST"])
@admin_required
def admin_optimize_tables():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (DB_CONFIG["database"],),
        )
        tables = [r["table_name"] for r in cur.fetchall()]
        for t in tables:
            try:
                cur.execute(f"OPTIMIZE TABLE `{t}`")
                cur.fetchall()
            except Exception:
                pass
        flash(f"Optimised {len(tables)} tables.", "success")
    except Exception as e:
        flash(f"Optimise failed: {e}", "danger")
    cur.close()
    conn.close()
    return redirect(url_for("admin_settings"))


@app.route("/api/admin/db-stats")
@admin_required
def api_admin_db_stats():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT table_name AS tn,
                      ROUND((data_length + index_length)/1024/1024, 3) AS size_mb,
                      table_rows AS rows
               FROM information_schema.tables
               WHERE table_schema = %s
               ORDER BY (data_length + index_length) DESC""",
            (DB_CONFIG["database"],),
        )
        tables = cur.fetchall()
    except Exception:
        tables = []
    cur.close()
    conn.close()
    total = sum(float(t["size_mb"] or 0) for t in tables)
    return jsonify({
        "tables": [{"name": t["tn"], "size_mb": float(t["size_mb"] or 0), "rows": t["rows"] or 0} for t in tables],
        "total_mb": round(total, 2),
        "db_name": DB_CONFIG["database"],
    })


# ═══════════════════════════════════════════════════════════════════════
# CHAT ROUTES & WEBSOCKETS
# ═══════════════════════════════════════════════════════════════════════

@app.route("/chat_admin", methods=["GET", "POST"])
@admin_required
def chat_admin_panel():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_user":
            full_name = request.form.get("full_name")
            email = request.form.get("email")
            password = request.form.get("password")
            role = request.form.get("role", "user")
            if full_name and email and password:
                try:
                    hashed_pw = generate_password_hash(password)
                    cur.execute("INSERT INTO users (full_name, email, password_hash, role, is_approved, is_active) VALUES (%s, %s, %s, %s, 1, 1)", (full_name, email, hashed_pw, role))
                    conn.commit()
                    flash("User added successfully.", "success")
                except Exception:
                    flash("Email already exists or error occurred.", "danger")
        elif action == "update_theme":
            theme_name = request.form.get("theme_name")
            if theme_name in PRESET_THEMES:
                theme_json = json.dumps(PRESET_THEMES[theme_name])
                cur.execute("SELECT id FROM admin_settings WHERE setting_key = 'global_theme'")
                if not cur.fetchone():
                    cur.execute("INSERT INTO admin_settings (setting_key, setting_value) VALUES ('global_theme', %s)", (theme_json,))
                else:
                    cur.execute("UPDATE admin_settings SET setting_value = %s WHERE setting_key = 'global_theme'", (theme_json,))
                conn.commit()
                flash(f"Global theme changed successfully to {theme_name}!", "success")
    
    # Calculate storage folder statistics
    upload_count = 0
    upload_size_mb = 0.0
    if os.path.exists(UPLOAD_FOLDER):
        for root, dirs, files in os.walk(UPLOAD_FOLDER):
            for file in files:
                upload_count += 1
                try:
                    upload_size_mb += os.path.getsize(os.path.join(root, file)) / (1024 * 1024)
                except Exception:
                    pass

    cur.execute("SELECT id, full_name, email, role FROM users ORDER BY id DESC")
    users = cur.fetchall()
    
    cur.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'global_theme'")
    theme_row = cur.fetchone()
    current_theme = json.loads(theme_row["setting_value"]) if theme_row else PRESET_THEMES["Sky Blue"]
    
    cur.close()
    conn.close()
    
    return render_template(
        "admin.html", 
        upload_folder=UPLOAD_FOLDER, 
        upload_count=upload_count, 
        upload_size_mb=round(upload_size_mb, 2), 
        users=users, 
        current_theme=current_theme, 
        preset_themes=PRESET_THEMES
    )

@app.route("/chat")
@login_required
def chat():
    return render_template("chat.html", current_user_id=session["user_id"], current_user_name=session["full_name"], role=session["role"])

@app.route("/api/users")
@login_required
def get_users():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, full_name, email, role, avatar_url, about FROM users WHERE id != %s AND is_active=1 AND is_approved=1", (session["user_id"],))
    users = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(users)

@app.route("/api/chat/recent")
@login_required
def get_recent_messages():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    # Get the latest message for every conversation
    cur.execute("""
        SELECT m.conversation_id, m.message_text, m.message_type 
        FROM messages m
        INNER JOIN (
            SELECT conversation_id, MAX(id) as max_id 
            FROM messages 
            GROUP BY conversation_id
        ) latest ON m.conversation_id = latest.conversation_id AND m.id = latest.max_id
    """)
    recents = cur.fetchall()
    cur.close()
    conn.close()
    
    recent_dict = {r['conversation_id']: (r['message_type'] if r['message_type'] != 'text' else r['message_text']) for r in recents}
    return jsonify(recent_dict)

@app.route("/api/chat/messages/<conversation_id>")
@login_required
def get_messages(conversation_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    
    before_id = request.args.get('before_id', type=int)
    limit = request.args.get('limit', default=40, type=int)
    
    # Check if the user cleared the chat history
    cur.execute("""
        SELECT cleared_up_to_message_id 
        FROM user_conversation_cleared 
        WHERE user_id = %s AND conversation_id = %s
    """, (session["user_id"], conversation_id))
    cleared_row = cur.fetchone()
    cleared_id = cleared_row["cleared_up_to_message_id"] if cleared_row else 0
    
    if before_id:
        cur.execute("""
            SELECT m.*, u.full_name as sender_name,
                   r.message_text as reply_text,
                   r.message_type as reply_type,
                   ru.full_name as reply_sender_name
            FROM messages m 
            JOIN users u ON m.sender_id = u.id 
            LEFT JOIN messages r ON m.reply_to_id = r.id
            LEFT JOIN users ru ON r.sender_id = ru.id
            LEFT JOIN deleted_messages_for_user dm ON m.id = dm.message_id AND dm.user_id = %s
            WHERE m.conversation_id = %s AND m.id < %s AND m.id > %s AND dm.id IS NULL
            ORDER BY m.id DESC
            LIMIT %s
        """, (session["user_id"], conversation_id, before_id, cleared_id, limit))
    else:
        cur.execute("""
            SELECT m.*, u.full_name as sender_name,
                   r.message_text as reply_text,
                   r.message_type as reply_type,
                   ru.full_name as reply_sender_name
            FROM messages m 
            JOIN users u ON m.sender_id = u.id 
            LEFT JOIN messages r ON m.reply_to_id = r.id
            LEFT JOIN users ru ON r.sender_id = ru.id
            LEFT JOIN deleted_messages_for_user dm ON m.id = dm.message_id AND dm.user_id = %s
            WHERE m.conversation_id = %s AND m.id > %s AND dm.id IS NULL
            ORDER BY m.id DESC
            LIMIT %s
        """, (session["user_id"], conversation_id, cleared_id, limit))
        
    messages = cur.fetchall()
    messages.reverse() # Reverse to chronological order (ascending)
    
    # Fetch reactions for all messages in this conversation
    msg_ids = [m["id"] for m in messages]
    reactions_map = {}
    if msg_ids:
        placeholders = ",".join(["%s"] * len(msg_ids))
        cur.execute(f"""
            SELECT mr.message_id, mr.emoji, mr.user_id, u.full_name
            FROM message_reactions mr
            JOIN users u ON mr.user_id = u.id
            WHERE mr.message_id IN ({placeholders})
        """, msg_ids)
        for r in cur.fetchall():
            mid = r["message_id"]
            if mid not in reactions_map:
                reactions_map[mid] = []
            reactions_map[mid].append({"emoji": r["emoji"], "user_id": r["user_id"], "user_name": r["full_name"]})
    
    for m in messages:
        if m["created_at"]:
            m["created_at"] = m["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        if m.get("file_url"):
            db_file_url = m["file_url"]
            if db_file_url == 'deleted':
                m["file_url"] = 'deleted'
            else:
                if db_file_url.startswith("/api/chat/download/"):
                    db_file_url = db_file_url[len("/api/chat/download/"):]
                m["file_url"] = f"/api/chat/download/{db_file_url}"
        m["reactions"] = reactions_map.get(m["id"], [])
    cur.close()
    conn.close()
    return jsonify(messages)

@app.route("/api/chat/groups", methods=["GET"])
@login_required
def get_groups():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT g.id, g.name, g.created_by 
        FROM chat_groups g
        JOIN chat_group_members m ON g.id = m.group_id
        WHERE m.user_id = %s
    """, (session["user_id"],))
    groups = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(groups)

@app.route("/api/chat/groups/<int:group_id>/members", methods=["GET"])
@login_required
def get_group_members(group_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT u.id, u.full_name, 
               COALESCE(m.role, 'member') as role
        FROM chat_group_members m
        JOIN users u ON m.user_id = u.id
        WHERE m.group_id = %s
    """, (group_id,))
    members = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(members)

@app.route("/api/chat/groups", methods=["POST"])
@login_required
def create_group():
    data = request.json
    name = data.get("name")
    user_ids = data.get("user_ids", [])
    
    if not name or not user_ids:
        return jsonify({"success": False, "message": "Name and users are required."}), 400
    
    # Check for duplicate group name
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM chat_groups WHERE LOWER(name) = LOWER(%s)", (name,))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "A group with this name already exists."}), 409
        
    if session["user_id"] not in user_ids:
        user_ids.append(session["user_id"])
    
    cur2 = conn.cursor()
    cur2.execute("INSERT INTO chat_groups (name, created_by) VALUES (%s, %s)", (name, session["user_id"]))
    group_id = cur2.lastrowid
    
    for uid in user_ids:
        role = 'admin' if uid == session["user_id"] else 'member'
        try:
            cur2.execute("INSERT INTO chat_group_members (group_id, user_id, role) VALUES (%s, %s, %s)", (group_id, uid, role))
        except Exception:
            cur2.execute("INSERT INTO chat_group_members (group_id, user_id) VALUES (%s, %s)", (group_id, uid))
        
    conn.commit()
    cur.close()
    cur2.close()
    conn.close()
    
    return jsonify({"success": True, "group_id": group_id, "name": name})

@app.route("/api/chat/messages/<int:msg_id>/pin", methods=["POST"])
@login_required
def toggle_pin(msg_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    
    cur.execute("SELECT is_pinned, conversation_id FROM messages WHERE id = %s", (msg_id,))
    msg = cur.fetchone()
    if not msg:
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Message not found"}), 404
        
    new_state = 0 if msg["is_pinned"] else 1
    cur.execute("UPDATE messages SET is_pinned = %s WHERE id = %s", (new_state, msg_id))
    conn.commit()
    
    cur.close()
    conn.close()
    
    socketio.emit('message_pinned', {
        'id': msg_id,
        'is_pinned': bool(new_state),
        'conversation_id': msg["conversation_id"]
    }, to=msg["conversation_id"])
    
    return jsonify({"success": True, "is_pinned": bool(new_state)})

@app.route("/api/chat/upload", methods=["POST"])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "No file part"}), 400
    
    file = request.files['file']
    conversation_id = request.form.get('conversation_id', 'unknown_chat')
    username = secure_filename(session.get('full_name', 'User'))
    
    save_dir = os.path.join(UPLOAD_FOLDER, username, conversation_id)
    try:
        os.makedirs(save_dir, exist_ok=True)
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to create storage directory: {str(e)}"}), 500
        
    filename = secure_filename(file.filename)
    save_path = os.path.join(save_dir, filename)
    
    # Handle name collisions by appending a number
    base, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(save_path):
        filename = f"{base}_{counter}{ext}"
        save_path = os.path.join(save_dir, filename)
        counter += 1
    
    file.save(save_path)
    
    relative_url = f"{username}/{conversation_id}/{filename}"
    
    return jsonify({
        "success": True, 
        "file_name": filename,
        "local_url": relative_url
    })


@app.route("/api/chat/upload-chunk", methods=["POST"])
@login_required
def upload_file_chunk():
    if 'chunk' not in request.files:
        return jsonify({"success": False, "message": "No chunk part"}), 400

    chunk = request.files['chunk']
    conversation_id = request.form.get('conversation_id', 'unknown_chat')
    filename = request.form.get('filename')
    upload_id = request.form.get('upload_id')
    chunk_index = request.form.get('chunk_index', type=int)
    total_chunks = request.form.get('total_chunks', type=int)

    if not filename or not upload_id or chunk_index is None or total_chunks is None:
        return jsonify({"success": False, "message": "Missing chunk metadata"}), 400

    username = secure_filename(session.get('full_name', 'User'))

    # Temporary directory for this specific upload session's chunks
    temp_chunk_dir = os.path.join(UPLOAD_FOLDER, username, conversation_id, f"tmp_{upload_id}")
    try:
        os.makedirs(temp_chunk_dir, exist_ok=True)
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to create temp directory: {str(e)}"}), 500

    chunk_filename = f"chunk_{chunk_index}"
    chunk_path = os.path.join(temp_chunk_dir, chunk_filename)
    chunk.save(chunk_path)

    # Check if we have received all chunks
    if chunk_index == total_chunks - 1:
        # Verify that all chunks exist
        all_chunks_received = True
        for i in range(total_chunks):
            p = os.path.join(temp_chunk_dir, f"chunk_{i}")
            if not os.path.exists(p):
                all_chunks_received = False
                break
        
        if all_chunks_received:
            # Final destination details
            save_dir = os.path.join(UPLOAD_FOLDER, username, conversation_id)
            os.makedirs(save_dir, exist_ok=True)
            
            final_filename = secure_filename(filename)
            save_path = os.path.join(save_dir, final_filename)
            
            # Handle name collisions by appending a number
            base, ext = os.path.splitext(final_filename)
            counter = 1
            while os.path.exists(save_path):
                final_filename = f"{base}_{counter}{ext}"
                save_path = os.path.join(save_dir, final_filename)
                counter += 1

            # Merge all chunks into the final destination
            try:
                with open(save_path, 'wb') as merged_file:
                    for i in range(total_chunks):
                        p = os.path.join(temp_chunk_dir, f"chunk_{i}")
                        with open(p, 'rb') as f:
                            merged_file.write(f.read())
                
                # Cleanup temp chunk files and directory
                for i in range(total_chunks):
                    p = os.path.join(temp_chunk_dir, f"chunk_{i}")
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                try:
                    os.rmdir(temp_chunk_dir)
                except Exception:
                    pass
                
                relative_url = f"{username}/{conversation_id}/{final_filename}"
                return jsonify({
                    "success": True,
                    "file_name": final_filename,
                    "local_url": relative_url,
                    "merged": True
                })
            except Exception as e:
                return jsonify({"success": False, "message": f"Failed to merge chunks: {str(e)}"}), 500
        else:
            return jsonify({"success": False, "message": "Missing some chunks, upload out of sync"}), 400

    return jsonify({"success": True, "chunk_received": chunk_index})

def find_file_fallback(base_path, filename):
    # Try direct path first
    direct_path = os.path.abspath(os.path.join(base_path, filename))
    if os.path.exists(direct_path):
        return direct_path
        
    # Search recursively for basename in UPLOAD_FOLDER
    base_name = os.path.basename(filename)
    if os.path.exists(UPLOAD_FOLDER):
        for root, dirs, files in os.walk(UPLOAD_FOLDER):
            if base_name in files:
                return os.path.abspath(os.path.join(root, base_name))
                
    # Fallback to historical uploads folder if present
    uploads_dir = os.path.abspath("uploads")
    if os.path.exists(uploads_dir):
        for root, dirs, files in os.walk(uploads_dir):
            if base_name in files:
                return os.path.abspath(os.path.join(root, base_name))
                
    return None

@app.route("/Images/<path:filename>")
def serve_images(filename):
    img_path = os.path.abspath(os.path.join("Images", filename))
    images_dir = os.path.abspath("Images")
    if img_path.startswith(images_dir) and os.path.exists(img_path):
        return send_file(img_path)
    return "Not Found", 404

@app.route("/api/chat/download/<path:filename>")
@login_required
def download_file(filename):
    resolved_path = find_file_fallback(UPLOAD_FOLDER, filename)
    as_attachment = request.args.get('download', '0') == '1'
    if resolved_path and os.path.exists(resolved_path):
        base = os.path.basename(resolved_path)
        return send_file(resolved_path, as_attachment=as_attachment, download_name=base)
        
    fallback_path = os.path.abspath(os.path.join(UPLOAD_FOLDER, filename))
    if os.path.exists(fallback_path):
        base = os.path.basename(filename)
        return send_file(fallback_path, as_attachment=as_attachment, download_name=base)
    return "File Not Found", 404

@app.route("/api/chat/open/<path:filename>")
@login_required
def open_file(filename):
    file_path = find_file_fallback(UPLOAD_FOLDER, filename)
    if not file_path or not os.path.exists(file_path):
        display_path = os.path.abspath(os.path.join(UPLOAD_FOLDER, filename))
        return jsonify({"success": False, "message": f"File not found at {display_path}"}), 404

    try:
        os.startfile(file_path)
        return jsonify({"success": True, "message": "File opened successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to open file: {str(e)}"}), 500

@app.route("/api/chat/save/<path:filename>")
@login_required
def save_file_dir(filename):
    file_path = find_file_fallback(UPLOAD_FOLDER, filename)
    if not file_path or not os.path.exists(file_path):
        display_path = os.path.abspath(os.path.join(UPLOAD_FOLDER, filename))
        return jsonify({"success": False, "message": f"File not found at {display_path}"}), 404

    try:
        import subprocess
        win_path = os.path.normpath(file_path)
        subprocess.Popen(f'explorer /select,"{win_path}"')
        return jsonify({"success": True, "message": "Directory opened successfully"})
    except Exception as e:
        try:
            os.startfile(os.path.dirname(file_path))
            return jsonify({"success": True, "message": "Directory opened successfully"})
        except Exception as ex:
            return jsonify({"success": False, "message": f"Failed to open directory: {str(ex)}"}), 500



# ─── GROUP MANAGEMENT ROUTES ────────────────────────────────────────

@app.route("/api/chat/groups/<int:group_id>/info", methods=["GET"])
@login_required
def get_group_info(group_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, name, created_by, created_at FROM chat_groups WHERE id = %s", (group_id,))
    group = cur.fetchone()
    if not group:
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Group not found"}), 404
    if group["created_at"]:
        group["created_at"] = group["created_at"].strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        SELECT u.id, u.full_name, COALESCE(m.role, 'member') as role
        FROM chat_group_members m
        JOIN users u ON m.user_id = u.id
        WHERE m.group_id = %s
    """, (group_id,))
    members = cur.fetchall()
    group["members"] = members
    cur.close()
    conn.close()
    return jsonify(group)

@app.route("/api/chat/groups/<int:group_id>/members", methods=["POST"])
@login_required
def add_group_members(group_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    # Check if requester is group admin
    cur.execute("SELECT role FROM chat_group_members WHERE group_id = %s AND user_id = %s", (group_id, session["user_id"]))
    member = cur.fetchone()
    if not member or member.get("role") != 'admin':
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Only group admins can add members."}), 403
    
    data = request.json
    user_ids = data.get("user_ids", [])
    added = []
    for uid in user_ids:
        try:
            cur.execute("INSERT INTO chat_group_members (group_id, user_id, role) VALUES (%s, %s, 'member')", (group_id, uid))
            added.append(uid)
        except Exception:
            pass
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True, "added": added})

@app.route("/api/chat/groups/<int:group_id>/members/<int:user_id>", methods=["DELETE"])
@login_required
def remove_group_member(group_id, user_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    # Check if requester is group admin or removing self
    cur.execute("SELECT role FROM chat_group_members WHERE group_id = %s AND user_id = %s", (group_id, session["user_id"]))
    requester = cur.fetchone()
    if not requester:
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "You are not a member of this group."}), 403
    
    is_self = (user_id == session["user_id"])
    if not is_self and requester.get("role") != 'admin':
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Only group admins can remove members."}), 403
    
    cur.execute("DELETE FROM chat_group_members WHERE group_id = %s AND user_id = %s", (group_id, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/chat/groups/<int:group_id>/members/<int:user_id>/make-admin", methods=["POST"])
@login_required
def make_group_admin(group_id, user_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT role FROM chat_group_members WHERE group_id = %s AND user_id = %s", (group_id, session["user_id"]))
    requester = cur.fetchone()
    if not requester or requester.get("role") != 'admin':
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Only admins can promote members."}), 403
    try:
        cur.execute("UPDATE chat_group_members SET role = 'admin' WHERE group_id = %s AND user_id = %s", (group_id, user_id))
    except Exception:
        pass
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/chat/groups/<int:group_id>/members/<int:user_id>/dismiss-admin", methods=["POST"])
@login_required
def dismiss_group_admin(group_id, user_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT role FROM chat_group_members WHERE group_id = %s AND user_id = %s", (group_id, session["user_id"]))
    requester = cur.fetchone()
    if not requester or requester.get("role") != 'admin':
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Only admins can dismiss admins."}), 403
    try:
        cur.execute("UPDATE chat_group_members SET role = 'member' WHERE group_id = %s AND user_id = %s", (group_id, user_id))
    except Exception:
        pass
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/chat/groups/<int:group_id>", methods=["DELETE"])
@login_required
def delete_group(group_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    
    # Check if creator
    cur.execute("SELECT created_by FROM chat_groups WHERE id = %s", (group_id,))
    group_row = cur.fetchone()
    is_creator = group_row and group_row["created_by"] == session["user_id"]
    
    # Check if admin
    cur.execute("SELECT role FROM chat_group_members WHERE group_id = %s AND user_id = %s", (group_id, session["user_id"]))
    requester = cur.fetchone()
    is_admin = requester and requester.get("role") == 'admin'
    
    if not is_creator and not is_admin:
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Only the group creator or admins can delete the group."}), 403
    
    try:
        room_name = f"group_{group_id}"
        cur.execute("DELETE FROM message_reactions WHERE message_id IN (SELECT id FROM messages WHERE conversation_id = %s)", (room_name,))
        cur.execute("DELETE FROM messages WHERE conversation_id = %s", (room_name,))
        cur.execute("DELETE FROM chat_group_members WHERE group_id = %s", (group_id,))
        cur.execute("DELETE FROM chat_groups WHERE id = %s", (group_id,))
        cur.execute("DELETE FROM pinned_conversations WHERE conversation_id = %s", (room_name,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": "Failed to delete group."}), 500
    
    cur.close()
    conn.close()
    socketio.emit('group_deleted', {'group_id': group_id}, room=room_name)
    return jsonify({"success": True})

@app.route("/api/chat/users/online", methods=["GET"])
@login_required
def get_online_users_api():
    return jsonify(list(online_users.keys()))

@app.route("/api/chat/users/statuses", methods=["GET"])
@login_required
def get_user_statuses_api():
    result = {}
    for uid in online_users.keys():
        result[uid] = user_custom_statuses.get(uid, 'online')
    return jsonify(result)


# ─── MESSAGE INFO ENDPOINT ───────────────────────────────────────────

@app.route("/api/chat/messages/<int:message_id>/info")
@login_required
def get_message_info(message_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    
    cur.execute("""
        SELECT m.id, m.conversation_id, m.sender_id, m.message_text, m.message_type,
               m.status, m.created_at, m.delivered_at, m.read_at,
               u.full_name as sender_name
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.id = %s
    """, (message_id,))
    msg = cur.fetchone()
    
    if not msg:
        cur.close()
        conn.close()
        return jsonify({"error": "Message not found"}), 404
    
    conv_id = msg['conversation_id']
    uid = session['user_id']
    
    def fmt(dt):
        return dt.strftime("%d %b %Y, %I:%M %p") if dt else None
    
    if conv_id.startswith('chat_'):
        parts = conv_id.split('_')
        if len(parts) == 3:
            try:
                uid1, uid2 = int(parts[1]), int(parts[2])
                if uid not in (uid1, uid2):
                    cur.close()
                    conn.close()
                    return jsonify({"error": "Unauthorized"}), 403
            except (ValueError, TypeError):
                cur.close()
                conn.close()
                return jsonify({"error": "Invalid conversation"}), 400
        
        result = {
            "type": "dm",
            "sender_name": msg['sender_name'],
            "status": msg['status'],
            "sent_at": fmt(msg['created_at']),
            "delivered_at": fmt(msg.get('delivered_at')),
            "read_at": fmt(msg.get('read_at'))
        }
    
    elif conv_id.startswith('group_'):
        try:
            group_id = int(conv_id.split('_')[1])
        except (ValueError, TypeError):
            cur.close()
            conn.close()
            return jsonify({"error": "Invalid group"}), 400
        
        cur.execute("SELECT 1 FROM chat_group_members WHERE group_id = %s AND user_id = %s", (group_id, uid))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Unauthorized"}), 403
        
        cur.execute("""
            SELECT mrr.user_id, u.full_name, mrr.read_at
            FROM message_read_receipts mrr
            JOIN users u ON mrr.user_id = u.id
            WHERE mrr.message_id = %s
            ORDER BY mrr.read_at ASC
        """, (message_id,))
        read_rows = cur.fetchall()
        
        cur.execute("""
            SELECT cgm.user_id, u.full_name
            FROM chat_group_members cgm
            JOIN users u ON cgm.user_id = u.id
            WHERE cgm.group_id = %s AND cgm.user_id != %s
        """, (group_id, msg['sender_id']))
        all_members = cur.fetchall()
        
        read_ids = {r['user_id'] for r in read_rows}
        not_read = [m for m in all_members if m['user_id'] not in read_ids]
        
        result = {
            "type": "group",
            "sender_name": msg['sender_name'],
            "sent_at": fmt(msg['created_at']),
            "read_by": [
                {"user_id": r['user_id'], "full_name": r['full_name'], "read_at": fmt(r['read_at'])}
                for r in read_rows
            ],
            "not_read_by": [
                {"user_id": m['user_id'], "full_name": m['full_name']}
                for m in not_read
            ]
        }
    else:
        cur.close()
        conn.close()
        return jsonify({"error": "Unknown conversation type"}), 400
    
    cur.close()
    conn.close()
    return jsonify(result)

# ─── USER PROFILE API ───────────────────────────────────────────────

@app.route("/api/chat/profile", methods=["GET"])
@login_required
def get_profile():
    uid = session["user_id"]
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, full_name, email, role, avatar_url, about FROM users WHERE id = %s", (uid,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404
        
    # Calculate UPLOAD_FOLDER storage size in MB
    storage_size_mb = 0.0
    try:
        username = secure_filename(user.get('full_name', 'User'))
        target_dir = UPLOAD_FOLDER if user.get("role") == "admin" else os.path.join(UPLOAD_FOLDER, username)
        if os.path.exists(target_dir):
            total_bytes = 0
            for root, dirs, files in os.walk(target_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.exists(fp):
                        total_bytes += os.path.getsize(fp)
            storage_size_mb = round(total_bytes / (1024 * 1024), 2)
    except Exception:
        pass

    return jsonify({
        "success": True,
        "full_name": user["full_name"],
        "email": user["email"],
        "role": user["role"],
        "avatar_url": user["avatar_url"],
        "about": user["about"],
        "storage_size_mb": storage_size_mb
    })

@app.route("/api/chat/profile", methods=["POST"])
@login_required
def update_profile():
    uid = session["user_id"]
    data = request.json
    full_name = data.get("full_name", "").strip()
    avatar_url = data.get("avatar_url", "").strip()
    about = data.get("about", "").strip()
    
    if not full_name:
        return jsonify({"success": False, "message": "Full name cannot be empty"}), 400
        
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            UPDATE users 
            SET full_name = %s, avatar_url = %s, about = %s 
            WHERE id = %s
        """, (full_name, avatar_url if avatar_url else None, about if about else "Available", uid))
        conn.commit()
        
        # Update session full_name so it renders instantly
        session["full_name"] = full_name
        
        # Broadcast the profile update using socketio (so other users' sidebars update real-time!)
        socketio.emit('profile_updated', {
            'user_id': uid,
            'full_name': full_name,
            'avatar_url': avatar_url,
            'about': about
        })
        
        return jsonify({"success": True, "message": "Profile updated successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/chat/profile/change-password", methods=["POST"])
@login_required
def change_password_api():
    uid = session["user_id"]
    data = request.json
    new_password = data.get("new_password", "").strip()
    
    if len(new_password) < 6:
        return jsonify({"success": False, "message": "Password must be at least 6 characters long"}), 400
        
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        pw_hash = generate_password_hash(new_password)
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (pw_hash, uid))
        conn.commit()
        return jsonify({"success": True, "message": "Password updated successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/chat/clear-storage", methods=["POST"])
@login_required
def clear_storage():
    try:
        import shutil
        if session.get("role") == "admin":
            if os.path.exists(UPLOAD_FOLDER):
                for filename in os.listdir(UPLOAD_FOLDER):
                    file_path = os.path.join(UPLOAD_FOLDER, filename)
                    try:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                    except Exception as e:
                        print(f"Failed to delete {file_path}: {e}")
                # Ensure the directory itself still exists
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        else:
            username = secure_filename(session.get('full_name', 'User'))
            user_dir = os.path.join(UPLOAD_FOLDER, username)
            if os.path.exists(user_dir):
                shutil.rmtree(user_dir)
                os.makedirs(user_dir, exist_ok=True)
        return jsonify({"success": True, "message": "Storage cleared successfully!"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ─── UNREAD NOTIFICATIONS API ───────────────────────────────────────

@app.route("/api/chat/unread-notifications", methods=["GET"])
@login_required
def get_unread_notifications():
    """Returns new unread messages for background notification polling."""
    uid = session["user_id"]
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT m.id, m.conversation_id, m.message_text, m.message_type, m.sender_id, u.full_name as sender_name
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.sender_id != %s 
              AND m.status != 'read'
              AND (m.conversation_id LIKE %s OR m.conversation_id LIKE %s 
                   OR m.conversation_id IN (
                       SELECT CONCAT('group_', group_id) 
                       FROM chat_group_members 
                       WHERE user_id = %s
                   ))
        """, (uid, f"chat\\_{uid}\\_%", f"chat\\_%\\_{uid}", uid))
        unread = cur.fetchall()
        return jsonify(unread)
    except Exception as e:
        print("Error getting unread notifications:", e)
        return jsonify([]), 500
    finally:
        cur.close()
        conn.close()


# ─── CONVERSATIONS API ──────────────────────────────────────────────

@app.route("/api/chat/conversations")
@login_required
def get_conversations():
    """Returns only conversations with at least one message, ordered by latest activity."""
    uid = session["user_id"]
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    
    # Bulk fetch cleared conversation maps
    cur.execute("SELECT conversation_id, cleared_up_to_message_id FROM user_conversation_cleared WHERE user_id = %s", (uid,))
    cleared_map = {r["conversation_id"]: r["cleared_up_to_message_id"] for r in cur.fetchall()}

    # Bulk fetch unread counts for DMs
    cur.execute("""
        SELECT m.conversation_id, COUNT(*) as cnt 
        FROM messages m
        LEFT JOIN user_conversation_cleared ucc ON ucc.user_id = %s AND ucc.conversation_id = m.conversation_id
        WHERE m.sender_id != %s AND m.status != 'read' 
          AND m.conversation_id LIKE 'chat_%'
          AND m.id > COALESCE(ucc.cleared_up_to_message_id, 0)
        GROUP BY m.conversation_id
    """, (uid, uid))
    unread_counts = {row["conversation_id"]: row["cnt"] for row in cur.fetchall()}

    # Bulk fetch group unread counts using last_read_at
    cur.execute("""
        SELECT m.conversation_id, COUNT(*) as cnt
        FROM messages m
        JOIN chat_group_members cgm ON m.conversation_id = CONCAT('group_', cgm.group_id)
        LEFT JOIN user_conversation_cleared ucc ON ucc.user_id = %s AND ucc.conversation_id = m.conversation_id
        WHERE cgm.user_id = %s 
          AND m.sender_id != %s 
          AND (cgm.last_read_at IS NULL OR m.created_at > cgm.last_read_at)
          AND m.id > COALESCE(ucc.cleared_up_to_message_id, 0)
        GROUP BY m.conversation_id
    """, (uid, uid, uid))
    for row in cur.fetchall():
        unread_counts[row["conversation_id"]] = row["cnt"]

    # Get DM conversations
    cur.execute("""
        SELECT m.conversation_id, m.message_text, m.message_type, m.created_at as last_time,
               m.sender_id, m.id as msg_id
        FROM messages m
        INNER JOIN (
            SELECT conversation_id, MAX(id) as max_id
            FROM messages
            WHERE conversation_id LIKE 'chat\\_%'
            GROUP BY conversation_id
        ) latest ON m.conversation_id = latest.conversation_id AND m.id = latest.max_id
        WHERE m.conversation_id LIKE %s OR m.conversation_id LIKE %s
        ORDER BY m.created_at DESC
    """, (f"chat\\_{uid}\\_%", f"chat\\_%\\_{uid}"))
    dm_convos = cur.fetchall()
    
    # Bulk fetch partner users
    partner_ids = []
    for c in dm_convos:
        parts = c["conversation_id"].split("_")
        if len(parts) == 3:
            uid1, uid2 = int(parts[1]), int(parts[2])
            partner_ids.append(uid2 if uid == uid1 else uid1)
            
    partners = {}
    if partner_ids:
        format_strings = ','.join(['%s'] * len(partner_ids))
        cur.execute(f"SELECT id, full_name, email, role, avatar_url, about FROM users WHERE id IN ({format_strings})", tuple(partner_ids))
        for row in cur.fetchall():
            partners[row["id"]] = row

    result = []
    for c in dm_convos:
        parts = c["conversation_id"].split("_")
        if len(parts) == 3:
            uid1, uid2 = int(parts[1]), int(parts[2])
            partner_id = uid2 if uid == uid1 else uid1
            partner = partners.get(partner_id)
            if partner:
                unread = unread_counts.get(c["conversation_id"], 0)
                cleared_id = cleared_map.get(c["conversation_id"], 0)
                if c["msg_id"] <= cleared_id:
                    continue  # Hide fully cleared/deleted DM chats
                
                last_text = c["message_text"] if c["message_type"] == "text" else ("📎 Attachment" if c["message_type"] == "file" else f"📎 {c['message_type']}")
                last_time_str = c["last_time"].strftime("%Y-%m-%d %H:%M:%S") if c["last_time"] else ""
                result.append({
                    "type": "dm",
                    "conversation_id": c["conversation_id"],
                    "partner_id": partner["id"],
                    "partner_name": partner["full_name"],
                    "partner_email": partner["email"],
                    "partner_role": partner["role"],
                    "partner_avatar": partner.get("avatar_url"),
                    "partner_about": partner.get("about", "Available"),
                    "last_message": last_text,
                    "last_time": last_time_str,
                    "unread": unread
                })
    
    # Get group conversations
    cur.execute("""
        SELECT g.id as group_id, g.name as group_name, g.created_by,
               m.message_text, m.message_type, m.created_at as last_time, m.id as msg_id
        FROM chat_groups g
        JOIN chat_group_members gm ON g.id = gm.group_id
        LEFT JOIN messages m ON m.conversation_id = CONCAT('group_', g.id)
            AND m.id = (SELECT MAX(id) FROM messages WHERE conversation_id = CONCAT('group_', g.id))
        WHERE gm.user_id = %s
        ORDER BY COALESCE(m.created_at, g.created_at) DESC
    """, (uid,))
    group_convos = cur.fetchall()
    
    for g in group_convos:
        conv_id = f"group_{g['group_id']}"
        unread = unread_counts.get(conv_id, 0)
        cleared_id = cleared_map.get(conv_id, 0)
        last_text = ""
        last_time_str = ""
        if g["msg_id"] and g["msg_id"] > cleared_id:
            if g["message_text"]:
                last_text = g["message_text"] if g["message_type"] == "text" else ("📎 Attachment" if g["message_type"] == "file" else f"📎 {g['message_type']}")
            last_time_str = g["last_time"].strftime("%Y-%m-%d %H:%M:%S") if g.get("last_time") else ""
        result.append({
            "type": "group",
            "conversation_id": conv_id,
            "partner_id": conv_id,
            "partner_name": g["group_name"],
            "group_id": g["group_id"],
            "created_by": g["created_by"],
            "last_message": last_text,
            "last_time": last_time_str,
            "unread": unread
        })
    
    # Sort all by last_time descending
    result.sort(key=lambda x: x.get("last_time", ""), reverse=True)
    
    # Check pinned conversations
    cur.execute("SELECT conversation_id FROM pinned_conversations WHERE user_id = %s", (uid,))
    pinned = {r["conversation_id"] for r in cur.fetchall()}
    for c in result:
        c["is_pinned"] = c["conversation_id"] in pinned
    
    cur.close()
    conn.close()
    return jsonify(result)

@app.route("/api/chat/search-users")
@login_required
def search_users():
    """Search all users by name for 'New Chat' flow."""
    q = request.args.get("q", "").strip()
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    if q:
        cur.execute("SELECT id, full_name, email, role, avatar_url, about FROM users WHERE id != %s AND is_active=1 AND is_approved=1 AND full_name LIKE %s", (session["user_id"], f"%{q}%"))
    else:
        cur.execute("SELECT id, full_name, email, role, avatar_url, about FROM users WHERE id != %s AND is_active=1 AND is_approved=1", (session["user_id"],))
    users = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(users)

# ─── PIN CONVERSATIONS ──────────────────────────────────────────────

@app.route("/api/chat/conversations/<path:conv_id>/pin", methods=["POST"])
@login_required
def toggle_pin_conversation(conv_id):
    uid = session["user_id"]
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM pinned_conversations WHERE user_id = %s AND conversation_id = %s", (uid, conv_id))
    existing = cur.fetchone()
    if existing:
        cur.execute("DELETE FROM pinned_conversations WHERE id = %s", (existing["id"],))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "is_pinned": False})
    else:
        # Max 3 pinned
        cur.execute("SELECT COUNT(*) as cnt FROM pinned_conversations WHERE user_id = %s", (uid,))
        count = cur.fetchone()["cnt"]
        if count >= 3:
            cur.close()
            conn.close()
            return jsonify({"success": False, "message": "Maximum 3 pinned conversations allowed."}), 400
        cur.execute("INSERT INTO pinned_conversations (user_id, conversation_id) VALUES (%s, %s)", (uid, conv_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "is_pinned": True})

# ─── LINK PREVIEW ───────────────────────────────────────────────────

@app.route("/api/chat/link-preview", methods=["POST"])
@login_required
def link_preview():
    url = (request.json or {}).get("url", "")
    if not url:
        return jsonify({"success": False}), 400

    # ─── SSRF protection: only allow public http(s) hosts ───
    try:
        from urllib.parse import urlparse
        import socket as _socket
        import ipaddress
        import html as _html

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return jsonify({"success": False}), 400

        # Resolve the host and reject private / loopback / link-local / reserved IPs.
        try:
            infos = _socket.getaddrinfo(parsed.hostname, None)
        except Exception:
            return jsonify({"success": False}), 400
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                return jsonify({"success": False}), 400
    except Exception:
        return jsonify({"success": False}), 400

    try:
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            html_text = response.read(4096).decode('utf-8', errors='ignore')
        title = ""
        desc = ""
        image = ""
        # Extract title
        t_match = re_module.search(r'<title[^>]*>([^<]+)</title>', html_text, re_module.IGNORECASE)
        if t_match:
            title = t_match.group(1).strip()
        # Extract og:title
        og_title = re_module.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html_text, re_module.IGNORECASE)
        if og_title:
            title = og_title.group(1).strip()
        # Extract og:description
        og_desc = re_module.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html_text, re_module.IGNORECASE)
        if og_desc:
            desc = og_desc.group(1).strip()
        # Extract og:image
        og_img = re_module.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html_text, re_module.IGNORECASE)
        if og_img:
            image = og_img.group(1).strip()
        # Decode HTML entities so the preview text is clean (client still escapes before display).
        return jsonify({
            "success": True,
            "title": _html.unescape(title),
            "description": _html.unescape(desc),
            "image": image if image.startswith(("http://", "https://")) else "",
        })
    except Exception:
        return jsonify({"success": False}), 500


def get_user_name_from_db(uid):
    conn = get_db()
    if not conn:
        return "A user"
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT full_name FROM users WHERE id = %s", (uid,))
        user = cur.fetchone()
        return user["full_name"] if user else "A user"
    except Exception:
        return "A user"
    finally:
        cur.close()
        conn.close()


@socketio.on('connect')
def on_connect():
    user_id = session.get('user_id')
    if not user_id:
        return
    sid = request.sid
    sid_to_uid[sid] = user_id
    is_new = False
    if user_id not in online_users:
        online_users[user_id] = set()
        is_new = True
    online_users[user_id].add(sid)
    if is_new:
        user_custom_statuses[user_id] = 'online'
        username = get_user_name_from_db(user_id)
        emit('user_status_changed', {'user_id': user_id, 'full_name': username, 'status': 'online'}, broadcast=True)

    # Personal room: lets us push new-chat notifications to a user even when
    # they have not opened (joined) that specific conversation room yet.
    join_room(f"user_{user_id}")

    # Mark all 'sent' messages to this user as 'delivered' (double check)
    conn = get_db()
    if conn:
        cur = conn.cursor()
        try:
            # We update all 'sent' messages in DMs where user_id is a participant and not the sender
            cur.execute("""
                UPDATE messages 
                SET status = 'delivered', delivered_at = NOW()
                WHERE status = 'sent' 
                  AND sender_id != %s 
                  AND (conversation_id LIKE %s OR conversation_id LIKE %s)
            """, (user_id, f"chat\\_{user_id}\\_%", f"chat\\_%\\_{user_id}"))
            conn.commit()
            
            # Find distinct conversation_ids that had updates to notify those senders
            cur.execute("""
                SELECT DISTINCT conversation_id 
                FROM messages 
                WHERE status = 'delivered' 
                  AND sender_id != %s 
                  AND (conversation_id LIKE %s OR conversation_id LIKE %s)
            """, (user_id, f"chat\\_{user_id}\\_%", f"chat\\_%\\_{user_id}"))
            updated_rooms = cur.fetchall()
            for r in updated_rooms:
                room_id = r[0]
                emit('messages_delivered', {'conversation_id': room_id, 'recipient_id': user_id}, room=room_id)
        except Exception as e:
            print("Error updating delivered statuses:", e)
        finally:
            cur.close()
            conn.close()

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    user_id = sid_to_uid.pop(sid, None)
    user_active_room.pop(sid, None)
    if user_id and user_id in online_users:
        online_users[user_id].discard(sid)
        if not online_users[user_id]:
            online_users.pop(user_id)
            user_custom_statuses.pop(user_id, None)
            username = get_user_name_from_db(user_id)
            emit('user_status_changed', {'user_id': user_id, 'full_name': username, 'status': 'offline'}, broadcast=True)

@socketio.on('change_status')
def handle_change_status(data):
    user_id = session.get('user_id')
    status = data.get('status')
    if not user_id or status not in ['online', 'away', 'offline']:
        return
    
    username = get_user_name_from_db(user_id)
    if status == 'offline':
        user_custom_statuses.pop(user_id, None)
        emit('user_status_changed', {'user_id': user_id, 'full_name': username, 'status': 'offline'}, broadcast=True)
    else:
        user_custom_statuses[user_id] = status
        emit('user_status_changed', {'user_id': user_id, 'full_name': username, 'status': status}, broadcast=True)

@socketio.on('join')
def on_join(data):
    room = data['conversation_id']
    sid = request.sid
    user_id = session.get('user_id')
    
    join_room(room)
    
    if user_id:
        user_active_room[sid] = room
        
        parts = room.split('_')
        
        conn = get_db()
        if conn:
            cur = conn.cursor()
            try:
                if len(parts) == 3 and parts[0] == 'chat':
                    uid1 = int(parts[1])
                    uid2 = int(parts[2])
                    recipient_id = uid2 if int(user_id) == uid1 else uid1
                    
                    cur.execute("""
                        UPDATE messages 
                        SET status = 'read', read_at = NOW()
                        WHERE conversation_id = %s AND sender_id = %s AND status != 'read'
                    """, (room, recipient_id))
                    conn.commit()
                    emit('messages_read', {'conversation_id': room, 'reader_id': user_id}, room=room)
                elif len(parts) == 2 and parts[0] == 'group':
                    group_id = int(parts[1])
                    cur.execute("""
                        UPDATE chat_group_members 
                        SET last_read_at = CURRENT_TIMESTAMP 
                        WHERE group_id = %s AND user_id = %s
                    """, (group_id, user_id))
                    # Record per-message read receipts for this group member
                    cur.execute("""
                        INSERT IGNORE INTO message_read_receipts (message_id, user_id, read_at)
                        SELECT m.id, %s, NOW()
                        FROM messages m
                        WHERE m.conversation_id = %s AND m.sender_id != %s
                    """, (user_id, f"group_{group_id}", user_id))
                    conn.commit()
            except Exception as e:
                print("Error updating read statuses:", e)
            finally:
                cur.close()
                conn.close()

@socketio.on('typing')
def on_typing(data):
    emit('user_typing', {
        'user_name': session.get('full_name'),
        'sender_id': session.get('user_id'),
        'conversation_id': data['conversation_id']
    }, room=data['conversation_id'], include_self=False)


def _is_conversation_participant(user_id, room):
    """Return True if user_id is allowed to post to this conversation room."""
    if not user_id or not room:
        return False
    parts = room.split('_')
    # Direct messages: chat_<a>_<b> — user must be one of the two ids.
    if len(parts) == 3 and parts[0] == 'chat':
        try:
            return int(user_id) in (int(parts[1]), int(parts[2]))
        except (ValueError, TypeError):
            return False
    # Groups: group_<id> — user must be a member.
    if len(parts) == 2 and parts[0] == 'group':
        try:
            gid = int(parts[1])
        except (ValueError, TypeError):
            return False
        conn = get_db()
        if not conn:
            return False
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT 1 FROM chat_group_members WHERE group_id = %s AND user_id = %s",
                (gid, user_id),
            )
            return cur.fetchone() is not None
        finally:
            cur.close()
            conn.close()
    return False


@socketio.on('send_message')
def handle_message(data):
    user_id = session.get('user_id')
    room = data.get('conversation_id')

    # Authorization: only participants may post to a conversation.
    if not _is_conversation_participant(user_id, room):
        return

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    
    reply_to_id = data.get('reply_to_id')
    file_url = data.get('file_url')
    is_forwarded = 1 if data.get('is_forwarded') else 0
    if file_url:
        if file_url.startswith("/api/chat/download/"):
            file_url = file_url[len("/api/chat/download/"):]
            
    status = 'sent'
    recipient_ids = []
    parts = room.split('_')
    if len(parts) == 3 and parts[0] == 'chat':
        uid1 = int(parts[1])
        uid2 = int(parts[2])
        recipient_id = uid2 if int(session['user_id']) == uid1 else uid1
        recipient_ids = [recipient_id]
        
        # Check if recipient is online
        if recipient_id in online_users:
            recipient_sids = online_users[recipient_id]
            is_in_room = False
            for sid in recipient_sids:
                if user_active_room.get(sid) == room:
                    is_in_room = True
                    break
            if is_in_room:
                status = 'read'
            else:
                status = 'delivered'
    elif parts[0] == 'group' and len(parts) == 2:
        # Notify all group members (except the sender) in their personal rooms.
        try:
            gid = int(parts[1])
            cur.execute("SELECT user_id FROM chat_group_members WHERE group_id = %s", (gid,))
            recipient_ids = [r["user_id"] for r in cur.fetchall() if int(r["user_id"]) != int(session['user_id'])]
        except Exception:
            recipient_ids = []
    
    if status == 'read':
        cur.execute(
            "INSERT INTO messages (conversation_id, sender_id, message_text, message_type, file_name, file_url, reply_to_id, is_forwarded, status, delivered_at, read_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())",
            (room, session['user_id'], data.get('text', ''), data.get('type', 'text'), data.get('file_name'), file_url, reply_to_id, is_forwarded, status)
        )
    elif status == 'delivered':
        cur.execute(
            "INSERT INTO messages (conversation_id, sender_id, message_text, message_type, file_name, file_url, reply_to_id, is_forwarded, status, delivered_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
            (room, session['user_id'], data.get('text', ''), data.get('type', 'text'), data.get('file_name'), file_url, reply_to_id, is_forwarded, status)
        )
    else:
        cur.execute(
            "INSERT INTO messages (conversation_id, sender_id, message_text, message_type, file_name, file_url, reply_to_id, is_forwarded, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (room, session['user_id'], data.get('text', ''), data.get('type', 'text'), data.get('file_name'), file_url, reply_to_id, is_forwarded, status)
        )
    msg_id = cur.lastrowid
    conn.commit()
    
    reply_text = None
    reply_type = None
    reply_sender_name = None
    
    if reply_to_id:
        cur.execute("""
            SELECT r.message_text, r.message_type, u.full_name 
            FROM messages r 
            JOIN users u ON r.sender_id = u.id 
            WHERE r.id = %s
        """, (reply_to_id,))
        r_msg = cur.fetchone()
        if r_msg:
            reply_text = r_msg["message_text"]
            reply_type = r_msg["message_type"]
            reply_sender_name = r_msg["full_name"]

    cur.close()
    conn.close()

    payload = {
        "id": msg_id,
        "conversation_id": room,
        "sender_name": session['full_name'],
        "sender_id": session['user_id'],
        "message_text": data.get('text', ''),
        "message_type": data.get('type', 'text'),
        "file_name": data.get('file_name'),
        "file_url": f"/api/chat/download/{file_url}" if file_url else None,
        "reply_to_id": reply_to_id,
        "reply_text": reply_text,
        "reply_type": reply_type,
        "reply_sender_name": reply_sender_name,
        "is_forwarded": is_forwarded,
        "status": status,
        "is_edited": 0,
        "reactions": [],
        "created_at": now_ist().strftime("%Y-%m-%d %H:%M:%S")
    }
    # Deliver to everyone currently viewing the conversation...
    emit('new_message', payload, room=room)
    # ...and to each recipient's personal room so chats they haven't opened still update live.
    # The client de-duplicates by message id, so receiving it twice is harmless.
    for rid in recipient_ids:
        emit('new_message', payload, room=f"user_{rid}")

@socketio.on('edit_message')
def handle_edit_message(data):
    msg_id = data.get('id')
    new_text = data.get('text', '').strip()
    room = data.get('conversation_id')
    user_id = session.get('user_id')
    
    if not msg_id or not new_text or not room or not user_id:
        return
        
    conn = get_db()
    if not conn:
        return
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT sender_id, message_type, created_at FROM messages WHERE id = %s", (msg_id,))
        msg = cur.fetchone()
        if msg:
            sender_id = msg['sender_id']
            msg_type = msg['message_type']
            created_at = msg['created_at']
            
            # Check 15 minute window
            diff = datetime.now() - created_at
            if sender_id == user_id and msg_type == 'text' and diff.total_seconds() < 15 * 60:
                cur.execute("UPDATE messages SET message_text = %s, is_edited = 1 WHERE id = %s", (new_text, msg_id))
                conn.commit()
                emit('message_edited', {'id': msg_id, 'text': new_text, 'conversation_id': room}, room=room)
    except Exception as e:
        print("Error editing message:", e)
    finally:
        cur.close()
        conn.close()

@socketio.on('delete_message')
def handle_delete_message(data):
    msg_id = data.get('id')
    room = data.get('conversation_id')
    delete_type = data.get('delete_type', 'everyone')
    if not msg_id or not room:
        return
        
    uid = session.get('user_id')
    if not uid:
        return
        
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    
    is_authorized = False
    if room.startswith("chat_"):
        parts = room.split("_")
        if len(parts) == 3:
            uid1, uid2 = int(parts[1]), int(parts[2])
            if uid == uid1 or uid == uid2:
                is_authorized = True
    elif room.startswith("group_"):
        try:
            group_id = int(room.split("_")[1])
            cur.execute("SELECT 1 FROM chat_group_members WHERE group_id = %s AND user_id = %s", (group_id, uid))
            if cur.fetchone():
                is_authorized = True
        except Exception:
            pass
            
    if is_authorized:
        cur.execute("SELECT id, sender_id, file_url FROM messages WHERE id = %s AND conversation_id = %s", (msg_id, room))
        msg = cur.fetchone()
        if msg:
            sender_id = msg['sender_id']
            is_deleted_placeholder = (msg['file_url'] == 'deleted')
            if delete_type == 'me' or is_deleted_placeholder:
                cur.execute("INSERT IGNORE INTO deleted_messages_for_user (user_id, message_id) VALUES (%s, %s)", (uid, msg_id))
                conn.commit()
                emit('message_physically_deleted', {'id': msg_id})
            else:
                if sender_id == uid:
                    cur.execute("DELETE FROM message_reactions WHERE message_id = %s", (msg_id,))
                    cur.execute("DELETE FROM message_read_receipts WHERE message_id = %s", (msg_id,))
                    cur.execute("""
                        UPDATE messages 
                        SET message_text = 'This message was deleted',
                            message_type = 'text',
                            file_url = 'deleted',
                            file_name = NULL,
                            reply_to_id = NULL,
                            is_pinned = 0,
                            is_edited = 0
                        WHERE id = %s
                    """, (msg_id,))
                    conn.commit()
                    emit('message_deleted', {'id': msg_id, 'sender_id': sender_id}, room=room)
            
    cur.close()
    conn.close()


@socketio.on('clear_chat')
def handle_clear_chat(data):
    room = data.get('conversation_id')
    if not room:
        return
        
    uid = session.get('user_id')
    if not uid:
        return
        
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    
    is_authorized = False
    
    if room.startswith("chat_"):
        parts = room.split("_")
        if len(parts) == 3:
            uid1, uid2 = int(parts[1]), int(parts[2])
            if uid == uid1 or uid == uid2:
                is_authorized = True
    elif room.startswith("group_"):
        try:
            group_id = int(room.split("_")[1])
            cur.execute("SELECT 1 FROM chat_group_members WHERE group_id = %s AND user_id = %s", (group_id, uid))
            if cur.fetchone():
                is_authorized = True
        except Exception:
            pass
            
    if is_authorized:
        try:
            # Query the maximum message ID currently in that room
            cur.execute("SELECT MAX(id) FROM messages WHERE conversation_id = %s", (room,))
            max_row = cur.fetchone()
            max_msg_id = max_row["MAX(id)"] if max_row and max_row["MAX(id)"] is not None else 0
            
            # Save or update the cleared boundary for this user
            cur.execute("""
                INSERT INTO user_conversation_cleared (user_id, conversation_id, cleared_up_to_message_id, cleared_at)
                VALUES (%s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE cleared_up_to_message_id = %s, cleared_at = NOW()
            """, (uid, room, max_msg_id, max_msg_id))
            conn.commit()
            
            # Emitting the chat_cleared event only to the requesting client
            emit('chat_cleared', {'conversation_id': room})
        except Exception as e:
            print("Error clearing chat:", e)
            
    cur.close()
    conn.close()


@socketio.on('react_message')
def handle_react_message(data):
    msg_id = data.get('message_id')
    emoji = data.get('emoji')
    room = data.get('conversation_id')
    user_id = session.get('user_id')
    user_name = session.get('full_name')
    
    if not msg_id or not emoji or not room or not user_id:
        return
    
    conn = get_db()
    if not conn:
        return
    cur = conn.cursor(dictionary=True)
    try:
        # Toggle reaction: if exists remove, else add
        cur.execute("SELECT id FROM message_reactions WHERE message_id = %s AND user_id = %s AND emoji = %s", (msg_id, user_id, emoji))
        existing = cur.fetchone()
        if existing:
            cur.execute("DELETE FROM message_reactions WHERE id = %s", (existing["id"],))
            action = 'removed'
        else:
            cur.execute("INSERT INTO message_reactions (message_id, user_id, emoji) VALUES (%s, %s, %s)", (msg_id, user_id, emoji))
            action = 'added'
        conn.commit()
        
        # Get the original message details to notify the sender
        cur.execute("SELECT sender_id, message_text FROM messages WHERE id = %s", (msg_id,))
        orig_msg = cur.fetchone()
        orig_sender_id = orig_msg["sender_id"] if orig_msg else None
        orig_text = orig_msg["message_text"] if orig_msg else ""
        
        # Fetch updated reactions for this message
        cur.execute("""
            SELECT mr.emoji, mr.user_id, u.full_name
            FROM message_reactions mr
            JOIN users u ON mr.user_id = u.id
            WHERE mr.message_id = %s
        """, (msg_id,))
        reactions = []
        for r in cur.fetchall():
            reactions.append({"emoji": r["emoji"], "user_id": r["user_id"], "user_name": r["full_name"]})
        
        emit('message_reacted', {
            'message_id': msg_id,
            'reactions': reactions,
            'conversation_id': room,
            'action': action,
            'reactor_id': user_id,
            'reactor_name': user_name,
            'orig_sender_id': orig_sender_id,
            'orig_text': orig_text,
            'emoji': emoji
        }, room=room)
    except Exception as e:
        print("Error handling reaction:", e)
    finally:
        cur.close()
        conn.close()


@socketio.on('call-user')
def handle_call_user(data):
    to_room = data.get('to')
    media_type = data.get('media_type', 'audio')
    offer = data.get('offer')
    caller_id = session.get('user_id')
    caller_name = session.get('full_name')
    if not to_room or not offer or not caller_id:
        return
    emit('call-made', {
        'offer': offer,
        'caller': caller_id,
        'caller_name': caller_name,
        'media_type': media_type
    }, room=to_room)


@socketio.on('make-answer')
def handle_make_answer(data):
    to_room = data.get('to')
    answer = data.get('answer')
    sender_id = session.get('user_id')
    if not to_room or not answer or not sender_id:
        return
    emit('answer-made', {
        'answer': answer,
        'sender': sender_id
    }, room=to_room)


@socketio.on('ice-candidate')
def handle_ice_candidate(data):
    to_room = data.get('to')
    candidate = data.get('candidate')
    sender_id = session.get('user_id')
    if not to_room or not candidate or not sender_id:
        return
    emit('ice-candidate', {
        'candidate': candidate,
        'sender': sender_id
    }, room=to_room)


@socketio.on('reject-call')
def handle_reject_call(data):
    to_room = data.get('to')
    sender_id = session.get('user_id')
    if not to_room or not sender_id:
        return
    emit('call-rejected', {
        'sender': sender_id
    }, room=to_room)


@socketio.on('end-call')
def handle_end_call(data):
    to_room = data.get('to')
    sender_id = session.get('user_id')
    if not to_room or not sender_id:
        return
    emit('call-ended', {
        'sender': sender_id
    }, room=to_room)


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def get_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

if __name__ == "__main__":
    init_db()

    scheduler_thread = threading.Thread(target=reminder_scheduler, daemon=True)
    scheduler_thread.start()

    run_host = os.environ.get("APP_HOST", "0.0.0.0")
    run_port = int(os.environ.get("PORT", os.environ.get("APP_PORT", 5501)))
    run_debug = os.environ.get("APP_DEBUG", "false").lower() in ("true", "1", "yes")

    local_ip = get_local_ip()

    print("")
    print("╔══════════════════════════════════════════════════╗")
    print("║           🚀 REYDM Server                       ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  Local:   http://127.0.0.1:{run_port}")
    if local_ip != '127.0.0.1':
        print(f"║  Network: http://{local_ip}:{run_port}")
    print(f"║  Debug:   {run_debug}")
    print(f"║  SMTP:    {SMTP_MODE} ({'port 465' if SMTP_MODE=='ssl' else 'port 587'})")
    print("╚══════════════════════════════════════════════════╝")
    print("")

    max_retries = 10
    for i in range(max_retries):
        try:
            socketio.run(app, debug=run_debug, host=run_host, port=run_port, allow_unsafe_werkzeug=True)
            break
        except OSError as e:
            if "10048" in str(e) or "Address already in use" in str(e) or "98" in str(e):
                print(f"⚠️ Port {run_port} is already in use. Trying port {run_port + 1}...")
                run_port += 1
            else:
                raise e
else:
    # Production / gunicorn — initialise DB and scheduler on import
    init_db()
    scheduler_thread = threading.Thread(target=reminder_scheduler, daemon=True)
    scheduler_thread.start()