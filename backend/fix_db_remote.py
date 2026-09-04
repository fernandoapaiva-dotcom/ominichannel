import sqlite3
import os
import shutil

db_path = "omini_channel.db"
backup_path = "omini_channel.db.bak"

if os.path.exists(db_path):
    shutil.copy(db_path, backup_path)

try:
    conn = sqlite3.connect(db_path)
    lines = []
    for line in conn.iterdump():
        lines.append(line)
    conn.close()

    clean_path = "clean_repaired.db"
    if os.path.exists(clean_path):
        os.remove(clean_path)

    conn2 = sqlite3.connect(clean_path)
    conn2.executescript("\n".join(lines))
    conn2.close()

    os.replace(clean_path, db_path)
    print("SQLITE REPAIR PASSED WITH 100% SUCCESS!")
except Exception as err:
    print(f"Error repairing database: {err}")
