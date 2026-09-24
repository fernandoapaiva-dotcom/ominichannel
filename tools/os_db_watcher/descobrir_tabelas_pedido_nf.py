"""
Script de descoberta - roda no computador da loja, usa o MESMO config.json do vigia de banco
(db_watcher.py) pra listar, direto no Firebird do Softsystem, quais tabelas/campos guardam
Pedido e Nota Fiscal. Só LEITURA (consulta o catálogo do sistema do Firebird, não mexe em nada).

Uso:
    python descobrir_tabelas_pedido_nf.py [nome_da_empresa]

Se não passar o nome da empresa, usa a primeira do config.json.
"""
import os
import sys
import json

from firebird.driver import connect, TPB, Isolation, TraAccessMode

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

# Palavras-chave pra achar as tabelas certas em meio a centenas de tabelas do Softsystem
KEYWORDS = ["PEDIDO", "VENDA", "NOTA", "NFISCAL", "NFE", "NFCE", "FATURA", "CAIXA"]


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def db_connect(empresa_cfg: dict):
    return connect(
        f"{empresa_cfg['host']}:{empresa_cfg['database']}",
        user=empresa_cfg.get("user", "SYSDBA"),
        password=empresa_cfg["password"],
        no_db_triggers=True,
        charset="WIN1252"
    )


def main():
    config = load_config()
    empresas = config.get("empresas") or config
    if isinstance(empresas, dict) and "host" in empresas:
        empresa_cfg = empresas
        nome = "(config raiz)"
    else:
        nome_pedido = sys.argv[1] if len(sys.argv) > 1 else None
        if nome_pedido and nome_pedido in empresas:
            nome, empresa_cfg = nome_pedido, empresas[nome_pedido]
        else:
            nome, empresa_cfg = next(iter(empresas.items()))

    print(f"Conectando na empresa: {nome} ({empresa_cfg.get('database')})\n")
    con = db_connect(empresa_cfg)
    tpb = TPB(access_mode=TraAccessMode.READ, isolation=Isolation.READ_COMMITTED_RECORD_VERSION)
    tra = con.transaction_manager(tpb.get_buffer())
    tra.begin()
    cur = tra.cursor()

    # 1. Lista tabelas cujo nome bate com alguma palavra-chave
    like_clauses = " OR ".join([f"RDB$RELATION_NAME LIKE '%{kw}%'" for kw in KEYWORDS])
    cur.execute(f"""
        SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS
        WHERE RDB$VIEW_BLR IS NULL AND RDB$SYSTEM_FLAG = 0 AND ({like_clauses})
        ORDER BY 1
    """)
    tables = [row[0] for row in cur.fetchall()]

    print(f"=== {len(tables)} tabela(s) encontrada(s) com esses nomes: ===")
    for t in tables:
        print(f"  - {t}")
    print()

    # 2. Pra cada tabela achada, lista as colunas (nome + tipo básico)
    for t in tables:
        cur.execute("""
            SELECT TRIM(rf.RDB$FIELD_NAME), f.RDB$FIELD_TYPE, f.RDB$FIELD_LENGTH
            FROM RDB$RELATION_FIELDS rf
            JOIN RDB$FIELDS f ON f.RDB$FIELD_NAME = rf.RDB$FIELD_SOURCE
            WHERE rf.RDB$RELATION_NAME = ?
            ORDER BY rf.RDB$FIELD_POSITION
        """, (t,))
        cols = cur.fetchall()
        print(f"--- {t} ({len(cols)} campo(s)) ---")
        for cname, ftype, flen in cols:
            print(f"    {cname}  (tipo={ftype}, tam={flen})")
        print()

    tra.commit()
    con.close()
    print("Pronto! Copie toda essa saída e mande de volta.")


if __name__ == "__main__":
    main()
