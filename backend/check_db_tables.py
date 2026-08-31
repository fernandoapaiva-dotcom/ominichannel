import os
import sqlite3

backup_dir = "/home/ubuntu/ominichannel/backend/backups_db"
files = [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith('.db')]
files.append("/home/ubuntu/ominichannel/backend/omini_channel.db")
files.append("/home/ubuntu/omini_channel.db")

print("Checking database files for tables...")
for f in sorted(files, key=os.path.getmtime, reverse=True):
    if not os.path.exists(f):
        continue
    try:
        conn = sqlite3.connect(f)
        c = conn.cursor()
        tables = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
        has_wn = "whatsapp_numbers" in tables
        has_users = "users" in tables
        user_count = c.execute("SELECT COUNT(*) FROM users;").fetchone()[0] if has_users else 0
        conv_count = c.execute("SELECT COUNT(*) FROM conversations;").fetchone()[0] if "conversations" in tables else 0
        print(f"File: {os.path.basename(f)} | Size: {os.path.getsize(f)} bytes | has_wn: {has_wn} | Users: {user_count} | Convs: {conv_count}")
        conn.close()
    except Exception as e:
        print(f"File: {os.path.basename(f)} Error: {e}")
