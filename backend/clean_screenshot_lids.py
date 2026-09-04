import sqlite3

conn = sqlite3.connect('omini_channel.db', timeout=60.0)
conn.execute('PRAGMA journal_mode=WAL;')
conn.execute('PRAGMA busy_timeout=60000;')
c = conn.cursor()

# 1. Update contact ID 40 to proper name
c.execute("UPDATE contacts SET nome = 'Cliente WhatsApp' WHERE id = 40")

# 2. Merge conversations from 4988 to 40
c.execute("UPDATE conversations SET contact_id = 40 WHERE contact_id = 4988")
c.execute("DELETE FROM contacts WHERE id = 4988")

# 3. Update contact 4543 name to 'MS metalúrgica santos'
c.execute("UPDATE contacts SET nome = 'MS metalúrgica santos' WHERE id = 4543")

# 4. Clean up any remaining numeric LID names across contacts table
c.execute("""
    UPDATE contacts 
    SET nome = 'Cliente WhatsApp' 
    WHERE (nome = telefone OR LENGTH(nome) >= 14)
      AND LENGTH(telefone) >= 14
      AND telefone NOT LIKE '55%'
      AND telefone NOT LIKE '120363%'
      AND telefone NOT LIKE '%-%'
""")

conn.commit()
conn.close()
print('WAL CLEANUP COMPLETED SUCCESSFULLY!')
