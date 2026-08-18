import sqlite3
import os

db_path = "omini_channel.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check columns in whatsapp_numbers
    cursor.execute("PRAGMA table_info(whatsapp_numbers)")
    cols = [row[1] for row in cursor.fetchall()]
    print("Existing columns in whatsapp_numbers:", cols)

    if "provider_type" not in cols:
        print("Adding provider_type column...")
        cursor.execute("ALTER TABLE whatsapp_numbers ADD COLUMN provider_type VARCHAR(20) NOT NULL DEFAULT 'evolution'")
    if "meta_phone_number_id" not in cols:
        print("Adding meta_phone_number_id column...")
        cursor.execute("ALTER TABLE whatsapp_numbers ADD COLUMN meta_phone_number_id VARCHAR(100)")
    if "meta_waba_id" not in cols:
        print("Adding meta_waba_id column...")
        cursor.execute("ALTER TABLE whatsapp_numbers ADD COLUMN meta_waba_id VARCHAR(100)")
    if "meta_access_token_encrypted" not in cols:
        print("Adding meta_access_token_encrypted column...")
        cursor.execute("ALTER TABLE whatsapp_numbers ADD COLUMN meta_access_token_encrypted TEXT")

    # Create tags table if not exists
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL,
        nome VARCHAR(50) NOT NULL,
        cor_hex VARCHAR(10) NOT NULL DEFAULT '#10b981',
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
    )
    """)

    # Create contact_segments table if not exists
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS contact_segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL,
        nome VARCHAR(100) NOT NULL,
        descricao VARCHAR(255),
        regras JSON NOT NULL,
        criado_em DATETIME NOT NULL,
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
    )
    """)

    # Create contact_tag_access table if not exists
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS contact_tag_access (
        contact_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL,
        PRIMARY KEY (contact_id, tag_id),
        FOREIGN KEY (contact_id) REFERENCES contacts (id) ON DELETE CASCADE,
        FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE
    )
    """)

    # Create whatsapp_groups table if not exists
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS whatsapp_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL,
        whatsapp_number_id INTEGER NOT NULL,
        group_jid VARCHAR(100) NOT NULL,
        nome VARCHAR(255) NOT NULL,
        ia_ativa BOOLEAN NOT NULL DEFAULT 0,
        criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
        FOREIGN KEY (whatsapp_number_id) REFERENCES whatsapp_numbers (id) ON DELETE CASCADE
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_groups_group_jid ON whatsapp_groups (group_jid)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_groups_tenant_id ON whatsapp_groups (tenant_id)")

    conn.commit()
    conn.close()
    print("DB SCHEMA FIXED SUCCESSFULLY!")

else:
    print("omini.db file not found in current directory.")
