import sqlite3
import random
import string
import os
from datetime import datetime, timedelta

# Render.com mount persistent disk ที่ /data
DATA_DIR = os.getenv("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "puxxza.db")

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS keys (
            key TEXT PRIMARY KEY,
            days INTEGER NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            discord_id TEXT,
            hwid TEXT,
            last_hwid_reset REAL
        );
        CREATE TABLE IF NOT EXISTS users (
            discord_id TEXT PRIMARY KEY,
            balance REAL DEFAULT 0.0
        );
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id TEXT PRIMARY KEY,
            discord_id TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at REAL NOT NULL,
            payment_type TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

def generate_key():
    chars = string.ascii_uppercase + string.digits
    suffix = ''.join(random.choices(chars, k=16))
    return f"puxxza-{suffix}"

def create_key(days: int) -> str:
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().timestamp()
    expires = (datetime.now() + timedelta(days=days)).timestamp()
    while True:
        key = generate_key()
        c.execute("SELECT key FROM keys WHERE key=?", (key,))
        if not c.fetchone():
            break
    c.execute("INSERT INTO keys VALUES (?,?,?,?,?,?,?)",
              (key, days, now, expires, None, None, None))
    conn.commit()
    conn.close()
    return key

def get_key(key: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_key(discord_id: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE discord_id=?", (discord_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def activate_key(key: str, discord_id: str) -> bool:
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE keys SET discord_id=? WHERE key=? AND discord_id IS NULL",
              (discord_id, key))
    updated = c.rowcount
    conn.commit()
    conn.close()
    return updated > 0

def get_all_keys():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM keys ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_key(key: str) -> bool:
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM keys WHERE key=?", (key,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted > 0

def cleanup_expired_keys() -> int:
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().timestamp()
    c.execute("DELETE FROM keys WHERE expires_at < ?", (now,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted

def verify_key_hwid(key: str, hwid: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE key=?", (key,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "KEY_NOT_FOUND"
    row = dict(row)
    now = datetime.now().timestamp()
    if now > row["expires_at"]:
        c.execute("DELETE FROM keys WHERE key=?", (key,))
        conn.commit()
        conn.close()
        return False, "KEY_EXPIRED"
    if row["hwid"] is None:
        c.execute("UPDATE keys SET hwid=? WHERE key=?", (hwid, key))
        conn.commit()
        conn.close()
        return True, "OK"
    if row["hwid"] == hwid:
        conn.close()
        return True, "OK"
    conn.close()
    return False, "HWID_MISMATCH"

def reset_hwid(discord_id: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE discord_id=?", (discord_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "NO_KEY"
    row = dict(row)
    now = datetime.now().timestamp()
    cooldown = 43200
    if row["last_hwid_reset"] and (now - row["last_hwid_reset"]) < cooldown:
        remaining = cooldown - (now - row["last_hwid_reset"])
        h = int(remaining // 3600)
        m = int((remaining % 3600) // 60)
        conn.close()
        return False, f"COOLDOWN:{h}:{m}"
    c.execute("UPDATE keys SET hwid=NULL, last_hwid_reset=? WHERE discord_id=?", (now, discord_id))
    conn.commit()
    conn.close()
    return True, "OK"

def get_user_balance(discord_id: str) -> float:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE discord_id=?", (discord_id,))
    row = c.fetchone()
    conn.close()
    return float(row["balance"]) if row else 0.0

def add_balance(discord_id: str, amount: float):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (discord_id, balance) VALUES (?,0)", (discord_id,))
    c.execute("UPDATE users SET balance = balance + ? WHERE discord_id=?", (amount, discord_id))
    conn.commit()
    conn.close()

def save_transaction(transaction_id: str, discord_id: str, amount: float, payment_type: str):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().timestamp()
    c.execute("INSERT OR IGNORE INTO transactions VALUES (?,?,?,?,?,?)",
              (transaction_id, discord_id, amount, "pending", now, payment_type))
    conn.commit()
    conn.close()

def complete_transaction(transaction_id: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE transactions SET status='completed' WHERE transaction_id=?", (transaction_id,))
    conn.commit()
    conn.close()

def get_transaction(transaction_id: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None
