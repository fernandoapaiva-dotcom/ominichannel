import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event, text
from app.core.config import settings

logger = logging.getLogger("database")

is_sqlite = "sqlite" in settings.DATABASE_URL.lower()

engine_kwargs = {
    "echo": False,
    "future": True,
}

if is_sqlite:
    from sqlalchemy.pool import NullPool
    engine_kwargs["poolclass"] = NullPool
    engine_kwargs["connect_args"] = {
        "timeout": 30.0,
        "check_same_thread": False,
    }
else:
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 30
    engine_kwargs["pool_recycle"] = 300

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs
)

if is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA busy_timeout=30000;")
            cursor.close()
        except Exception as e:
            logger.debug(f"SQLite PRAGMA error: {e}")

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

from sqlalchemy import text

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        migrations = [
            "ALTER TABLE contacts ADD COLUMN foto_perfil_url VARCHAR(500);",
            "ALTER TABLE os_technician_copilot_messages ADD COLUMN documento_busca VARCHAR(120);",
            "ALTER TABLE authorized_technicians ADD COLUMN cargo VARCHAR(100);",
            "ALTER TABLE authorized_technicians ADD COLUMN departamento VARCHAR(100);",
            "ALTER TABLE calendar_events ADD COLUMN event_type VARCHAR(50) DEFAULT 'geral';",
            "ALTER TABLE os_board_orders ADD COLUMN venda_codigo INTEGER;",
            "ALTER TABLE os_board_orders ADD COLUMN telefone VARCHAR(20);",
            "ALTER TABLE os_board_orders ADD COLUMN contato_nome VARCHAR(120);",
            "ALTER TABLE os_board_orders ADD COLUMN last_nudge_at DATETIME;",
            "ALTER TABLE os_board_orders ADD COLUMN valor_total FLOAT;",
            "ALTER TABLE os_board_orders ADD COLUMN forma_pagamento VARCHAR(60);",
            "ALTER TABLE calendar_events ADD COLUMN employee_id INTEGER;",
            "ALTER TABLE calendar_events ADD COLUMN employee_name VARCHAR(150);",
            "ALTER TABLE calendar_events ADD COLUMN employee_phone VARCHAR(50);",
            "ALTER TABLE calendar_events ADD COLUMN notify_whatsapp BOOLEAN DEFAULT 1;",
            "ALTER TABLE calendar_events ADD COLUMN notified_creation BOOLEAN DEFAULT 0;",
            "ALTER TABLE calendar_events ADD COLUMN notified_day_of BOOLEAN DEFAULT 0;",
            "ALTER TABLE calendar_events ADD COLUMN notified_hours_before BOOLEAN DEFAULT 0;",
            "ALTER TABLE calendar_events ADD COLUMN custom_reminder_hours INTEGER DEFAULT 2;",
            "ALTER TABLE calendar_events ADD COLUMN confirmed_by_employee BOOLEAN DEFAULT 0;",
            "ALTER TABLE calendar_events ADD COLUMN confirmed_at DATETIME;",
            "ALTER TABLE calendar_events ADD COLUMN confirmation_token VARCHAR(100);",
            "ALTER TABLE calendar_events ADD COLUMN whatsapp_number_id INTEGER;",
            "ALTER TABLE calendar_events ADD COLUMN whatsapp_instance VARCHAR(100);",
            "ALTER TABLE calendar_events ADD COLUMN contact_name VARCHAR(200);",
            "ALTER TABLE calendar_events ADD COLUMN contact_phone VARCHAR(50);",
            "ALTER TABLE os_board_orders ADD COLUMN equip_obs_raw TEXT;",
            "ALTER TABLE softsystem_pending_writes ADD COLUMN suppress_customer_notice BOOLEAN DEFAULT 0;",
            # Compras & Balcão - parâmetros fiscais por loja, conferência cega e auditoria (13/10/2026)
            "ALTER TABLE loja_parametros_custo ADD COLUMN margem_minima_pct FLOAT;",
            "ALTER TABLE loja_parametros_custo ADD COLUMN icms_saida_pct FLOAT;",
            "ALTER TABLE loja_parametros_custo ADD COLUMN pis_saida_pct FLOAT;",
            "ALTER TABLE loja_parametros_custo ADD COLUMN cofins_saida_pct FLOAT;",
            "ALTER TABLE loja_parametros_custo ADD COLUMN irpj_csll_pct FLOAT;",
            "ALTER TABLE loja_parametros_custo ADD COLUMN das_pct FLOAT;",
            "ALTER TABLE loja_parametros_custo ADD COLUMN das_parcela_icms_pct FLOAT;",
            "ALTER TABLE loja_parametros_custo ADD COLUMN icms_antecipacao_pct FLOAT;",
            "ALTER TABLE loja_parametros_custo ADD COLUMN faturamento_medio_mensal FLOAT;",
            "ALTER TABLE loja_parametros_custo ADD COLUMN condicao_pagamento_padrao VARCHAR(50);",
            "ALTER TABLE compras_entradas ADD COLUMN transportadora_cnpj VARCHAR(20);",
            "ALTER TABLE compras_entradas ADD COLUMN transportadora_nome VARCHAR(255);",
            "ALTER TABLE compras_entradas ADD COLUMN serie VARCHAR(10);",
            "ALTER TABLE compras_entradas ADD COLUMN valor_frete_nota FLOAT DEFAULT 0;",
            "ALTER TABLE compras_entradas ADD COLUMN valor_frete_extra_transportadora FLOAT DEFAULT 0;",
            "ALTER TABLE compras_entradas ADD COLUMN tipo_rateio_frete VARCHAR(20) DEFAULT 'valor';",
            "ALTER TABLE compras_entradas ADD COLUMN valor_despesas_acessorias FLOAT DEFAULT 0;",
            "ALTER TABLE compras_entradas ADD COLUMN origem_xml VARCHAR(30);",
            "ALTER TABLE compras_entradas ADD COLUMN nota_json TEXT;",
            "ALTER TABLE compras_entradas ADD COLUMN cte_chave VARCHAR(50);",
            "ALTER TABLE compras_entradas ADD COLUMN cte_numero VARCHAR(20);",
            "ALTER TABLE compras_entradas ADD COLUMN valor_frete_cte FLOAT DEFAULT 0;",
            "ALTER TABLE compras_entradas ADD COLUMN valor_icms_cte FLOAT DEFAULT 0;",
            "ALTER TABLE compras_entradas ADD COLUMN despesas_extras_json TEXT;",
            "ALTER TABLE compras_entradas ADD COLUMN parcelas_json TEXT;",
            "ALTER TABLE compras_entradas ADD COLUMN parcelas_cte_json TEXT;",
            "ALTER TABLE compras_entradas ADD COLUMN conferencia_iniciada_em DATETIME;",
            "ALTER TABLE compras_entradas ADD COLUMN conferencia_finalizada_em DATETIME;",
            "ALTER TABLE compras_entradas ADD COLUMN conferente VARCHAR(100);",
            "ALTER TABLE compras_entradas ADD COLUMN divergencia_aprovada_por VARCHAR(100);",
            "ALTER TABLE compras_entradas ADD COLUMN divergencia_justificativa TEXT;",
            "ALTER TABLE compras_entradas ADD COLUMN fechada_em DATETIME;",
            "ALTER TABLE compras_entradas ADD COLUMN fechada_por VARCHAR(100);",
            "ALTER TABLE compras_entradas ADD COLUMN softsystem_codcompra INTEGER;",
            "ALTER TABLE compras_entrada_itens ADD COLUMN fator_conversao FLOAT DEFAULT 1;",
            "ALTER TABLE compras_entrada_itens ADD COLUMN qtd_contada FLOAT;",
            "ALTER TABLE compras_entrada_itens ADD COLUMN contado_por VARCHAR(100);",
            "ALTER TABLE compras_entrada_itens ADD COLUMN contado_em DATETIME;",
            "ALTER TABLE compras_entrada_itens ADD COLUMN recontagens INTEGER DEFAULT 0;",
            "ALTER TABLE compras_entrada_itens ADD COLUMN vinculo_metodo VARCHAR(30);",
            "ALTER TABLE compras_entrada_itens ADD COLUMN produto_modelo_codigo VARCHAR(50);",
            "ALTER TABLE compras_entrada_itens ADD COLUMN calculo_json TEXT;",
            # Entrada de nota - CT-e no Softsystem + auditoria de estoque/localização (15/10/2026)
            "ALTER TABLE compras_entradas ADD COLUMN cte_json TEXT;",
            "ALTER TABLE compras_entradas ADD COLUMN pasta_notas VARCHAR(300);",
            "ALTER TABLE catalogo_midias ADD COLUMN softsystem_codimagem INTEGER;",
            "ALTER TABLE compras_entrada_itens ADD COLUMN estoque_auditado FLOAT;",
            "ALTER TABLE compras_entrada_itens ADD COLUMN cadastro_novo_json TEXT;",
            "ALTER TABLE compras_entrada_itens ADD COLUMN auditado_por VARCHAR(100);",
            "ALTER TABLE compras_entrada_itens ADD COLUMN auditado_em DATETIME;",
            "ALTER TABLE compras_entrada_itens ADD COLUMN localizacao_estoque VARCHAR(100);",
            "ALTER TABLE compras_entrada_itens ADD COLUMN synced_softsystem BOOLEAN DEFAULT 0;",
            "ALTER TABLE compras_entrada_itens ADD COLUMN synced_ecommerce BOOLEAN DEFAULT 0;",
        ]
        for sql in migrations:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass
