import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "OminiChannel WhatsApp"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "SUPER_SECRET_JWT_KEY_CHANGE_IN_PRODUCTION_12345"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Database (Absolute path to ensure correct file loading)
    DATABASE_URL: str = f"sqlite+aiosqlite:///{os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'omini_channel.db')}"
    
    # Evolution API (Self-Hosted)
    EVOLUTION_API_URL: str = os.getenv("EVOLUTION_API_URL", "http://ominichannel.duckdns.org:8080")
    EVOLUTION_API_KEY: str = os.getenv("EVOLUTION_API_KEY", "omini_master_key_123")

    # Webhook base URL (used by Evolution API to send events back to this server)
    # In OCI/production, set this to your public domain, e.g. https://ominichannel.duckdns.org
    # In local Docker, use http://host.docker.internal:8000
    WEBHOOK_BASE_URL: str = "http://host.docker.internal:8000"

    # Gemini AI
    GEMINI_API_KEY: str = ""

    # Google Drive Integration
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"

    # OS Handler PDF ingestion (external "folder watcher" running on the shop's own PC posts
    # the Softsystem O.S. PDF here). No user is logged in on that side, so it authenticates
    # with this shared secret instead of a JWT - set a real random value in production .env
    # (e.g. `openssl rand -hex 32`), never keep the placeholder default.
    OS_HANDLER_INGEST_API_KEY: str = os.getenv("OS_HANDLER_INGEST_API_KEY", "CHANGE_ME_OS_HANDLER_KEY")
    # WhatsAppNumber.id of the Assistência Técnica department/instance - fixed target for
    # every O.S. PDF ingested (the folder watcher never sends this, it's always the same shop).
    ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID: int = int(os.getenv("ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID", "2"))
    # WhatsApp group JID for "SERV - SOLICITAÇÃO DE O.S." - where the customer's
    # approval/rejection of the technician's quote gets announced (fase 2 do OS Handler).
    SERV_OS_GROUP_JID: str = os.getenv("SERV_OS_GROUP_JID", "120363423806324709@g.us")

    # Compras - NF-e de entrada.
    # Pastas onde o Softsystem salva os XMLs (separadas por ";"). Na VM Linux, apontar para o
    # ponto de montagem CIFS do \\SRV-SERVWELD (ex: /mnt/srv-servweld/NFe/xml;/mnt/srv-servweld/NFe_LOJA02/Xml).
    NFE_XML_DIRS: str = os.getenv("NFE_XML_DIRS", r"\\SRV-SERVWELD\NFe\xml;\\SRV-SERVWELD\NFe_LOJA02\Xml")
    # Cache local dos XMLs baixados da SEFAZ (nunca consultar a mesma chave duas vezes - a SEFAZ
    # bloqueia o CNPJ por "consumo indevido" quando repete consulta).
    NFE_XML_CACHE_DIR: str = os.getenv(
        "NFE_XML_CACHE_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads", "nfe_xml"),
    )
    # Certificados A1 (.pfx) de cada loja, para buscar a nota na SEFAZ (Distribuição DF-e).
    # O normal é enviar pela tela (Compras > Parâmetros): o .pfx vai para NFE_CERT_DIR e a senha
    # é gravada criptografada. As variáveis abaixo são alternativa via .env - nunca no Git.
    NFE_CERT_DIR: str = os.getenv(
        "NFE_CERT_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "certificados"),
    )
    NFE_CERT_SERVWELD_PATH: str = os.getenv("NFE_CERT_SERVWELD_PATH", "")
    NFE_CERT_SERVWELD_SENHA: str = os.getenv("NFE_CERT_SERVWELD_SENHA", "")
    NFE_CERT_CENTROOESTE_PATH: str = os.getenv("NFE_CERT_CENTROOESTE_PATH", "")
    NFE_CERT_CENTROOESTE_SENHA: str = os.getenv("NFE_CERT_CENTROOESTE_SENHA", "")
    # 1 = produção, 2 = homologação
    NFE_AMBIENTE: int = int(os.getenv("NFE_AMBIENTE", "1"))
    # Lançamento da entrada no Softsystem (compra, contas a pagar, estoque, preço) - ver
    # softsystem_compra_writer.py. "desligado" (padrão) | "teste" (grava só na cópia abaixo) | "producao"
    SOFTSYSTEM_COMPRAS_MODO: str = os.getenv("SOFTSYSTEM_COMPRAS_MODO", "desligado")
    SOFTSYSTEM_COMPRAS_DB_TESTE: str = os.getenv("SOFTSYSTEM_COMPRAS_DB_TESTE", "")
    # Catálogo do site (etapas 5/6): pasta onde o Softsystem guarda as fotos ("Produto {cod} {img}.jpg",
    # CONFIGURACAO.DIRETORIOIMAGENS = Z:\SOFTSYSTEM\Arquivos) montada na VM, para importar as fotos que já existem.
    SOFTSYSTEM_IMAGENS_DIR_SERVWELD: str = os.getenv("SOFTSYSTEM_IMAGENS_DIR_SERVWELD", "")
    SOFTSYSTEM_IMAGENS_DIR_CENTROOESTE: str = os.getenv("SOFTSYSTEM_IMAGENS_DIR_CENTROOESTE", "/mnt/softsystem_arquivos_centrooeste")
    # Via da nota de fornecedor (XML + DANFE) arquivada no lançamento: ANO/MÊS/FORNECEDOR/N.F x
    # (Z:\Documentos\NOTAS FISCAIS- FORNECEDORES da Servweld). Vazio = não arquiva.
    NOTAS_FORNECEDORES_DIR_SERVWELD: str = os.getenv(
        "NOTAS_FORNECEDORES_DIR_SERVWELD", "/mnt/softsystem_drive/Documentos/NOTAS FISCAIS- FORNECEDORES")
    NOTAS_FORNECEDORES_DIR_CENTROOESTE: str = os.getenv("NOTAS_FORNECEDORES_DIR_CENTROOESTE", "")
    # Site público (Hostinger) lê /api/v1/public/site: endereço público das fotos e de qual loja é o catálogo
    SITE_PUBLIC_BASE_URL: str = os.getenv("SITE_PUBLIC_BASE_URL", "https://app.servweld.com.br")
    SITE_EMPRESA: str = os.getenv("SITE_EMPRESA", "servweld")
    SITE_TENANT_ID: int = int(os.getenv("SITE_TENANT_ID", "1"))

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
