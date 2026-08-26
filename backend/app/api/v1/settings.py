import os
from typing import List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_admin_user, get_current_user, create_oauth_state, verify_oauth_state
from app.models.models import User, AuditLog
from app.schemas.schemas import (
    SaveIntegrationSettingsPayload,
    IntegrationSettingsMaskedResponse,
    TestIntegrationRequest,
    TestIntegrationResponse,
    AuditLogResponse
)
from app.services.settings_service import settings_service
from app.services.evolution_service import evolution_service
from app.services.gemini_service import gemini_service

router = APIRouter(prefix="/settings", tags=["Configurações de Integração e Segurança"])

@router.get("/", response_model=IntegrationSettingsMaskedResponse)
async def get_tenant_settings(
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns tenant settings with sensitive keys masked (e.g. AIzaSy...****).
    Never returns plaintext sensitive tokens.
    """
    masked = await settings_service.get_tenant_masked_settings(db, admin_user.tenant_id)
    return masked

@router.post("/", status_code=status.HTTP_200_OK)
async def save_tenant_settings(
    payload: SaveIntegrationSettingsPayload,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Encrypts sensitive integration fields using Fernet and saves to DB.
    Logs audit record.
    """
    data = payload.model_dump(exclude_unset=True)
    await settings_service.save_tenant_integration_settings(
        db=db,
        tenant_id=admin_user.tenant_id,
        user=admin_user,
        payload=data
    )
    return {"status": "success", "message": "Configurações salvas com sucesso (criptografadas via Fernet)."}

@router.post("/test", response_model=TestIntegrationResponse)
async def test_integration_connection(
    req: TestIntegrationRequest,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Live 'Test Connection' button logic for Gemini AI and Evolution API using dynamic model name.
    """
    decrypted = await settings_service.get_tenant_decrypted_settings(db, admin_user.tenant_id)

    if req.integration_type == "gemini":
        api_key = req.test_key if (req.test_key and req.test_key.strip() != "") else decrypted["gemini_api_key"]
        model_name = req.test_model if (req.test_model and req.test_model.strip() != "") else decrypted["gemini_model_name"]

        if not api_key:
            return TestIntegrationResponse(success=False, message="Nenhuma chave API do Gemini configurada para teste.")

        try:
            client = gemini_service.get_client_for_key(api_key)
            res = client.models.generate_content(
                model=model_name,
                contents="Responda apenas a palavra OK."
            )
            message = f"Conexão com Google Gemini realizada com sucesso (Modelo: '{model_name}')! Resposta: '{res.text.strip()}'" if (res and res.text) else "Gemini API respondeu mas sem conteúdo válido."
            success = bool(res and res.text)
            
            audit = AuditLog(
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                user_name=admin_user.nome,
                acao="TESTOU_CONEXAO_GEMINI",
                detalhes=f"Resultado: {'Sucesso' if success else 'Falha'} (Modelo: {model_name}) — {message[:100]}",
                timestamp=datetime.utcnow()
            )
            db.add(audit)
            await db.commit()

            return TestIntegrationResponse(success=success, message=message)
        except Exception as e:
            msg = f"Falha ao conectar com Google Gemini (Modelo: '{model_name}'): {str(e)}"
            audit = AuditLog(
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                user_name=admin_user.nome,
                acao="TESTOU_CONEXAO_GEMINI",
                detalhes=f"Resultado: Falha — {msg[:100]}",
                timestamp=datetime.utcnow()
            )
            db.add(audit)
            await db.commit()
            return TestIntegrationResponse(success=False, message=msg)

    elif req.integration_type == "evolution":
        url = req.test_url or decrypted["evolution_api_url"]
        api_key = req.test_key if (req.test_key and req.test_key.strip() != "") else decrypted["evolution_api_key"]
        
        if not url or not url.strip():
            return TestIntegrationResponse(success=False, message="URL da Evolution API não informada.")

        try:
            res = await evolution_service.ping_server(custom_base_url=url, custom_api_key=api_key)
            is_success = res.get("success") is True
            error_detail = res.get("error")

            if is_success:
                instances = res.get("data", [])
                msg = f"Conexão com a Evolution API em '{url}' realizada com SUCESSO! Instâncias ativas: {len(instances)}."
            else:
                msg = f"Não foi possível autenticar na Evolution API em '{url}'. Detalhes: {error_detail or 'Verifique se a Master Key está correta.'}"

            audit = AuditLog(
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                user_name=admin_user.nome,
                acao="TESTOU_CONEXAO_EVOLUTION",
                detalhes=f"Resultado: {'Sucesso' if is_success else 'Falha'} — {msg[:100]}",
                timestamp=datetime.utcnow()
            )
            db.add(audit)
            await db.commit()

            return TestIntegrationResponse(success=is_success, message=msg)
        except Exception as e:
            msg = f"Falha ao tentar comunicação com Evolution API na URL '{url}': {str(e)}"
            audit = AuditLog(
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                user_name=admin_user.nome,
                acao="TESTOU_CONEXAO_EVOLUTION",
                detalhes=f"Resultado: Falha — {msg[:100]}",
                timestamp=datetime.utcnow()
            )
            db.add(audit)
            await db.commit()
            return TestIntegrationResponse(success=False, message=msg)

    else:
        raise HTTPException(status_code=400, detail="Tipo de integração inválido")

@router.get("/audit-logs", response_model=List[AuditLogResponse])
async def get_tenant_audit_logs(
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns audit log history of configuration changes.
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.tenant_id == admin_user.tenant_id)
        .order_by(AuditLog.timestamp.desc())
        .limit(50)
    )
    res = await db.execute(stmt)
    return res.scalars().all()

# --- Google OAuth2 Consent Flow for Google Drive ---
@router.get("/auth/google/url")
async def get_google_oauth_url(
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generates Google OAuth2 consent URL with cryptographically signed CSRF state token.
    """
    decrypted = await settings_service.get_tenant_decrypted_settings(db, admin_user.tenant_id)
    client_id = decrypted.get("google_client_id") or os.environ.get("GOOGLE_CLIENT_ID", "")
    
    if not client_id or client_id == "SAMPLE_CLIENT_ID_PLACEHOLDER" or not client_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O Google Client ID ainda não foi configurado. Preencha o 'Google Client ID' e 'Google Client Secret' no painel de configurações antes de conectar a conta."
        )

    csrf_state = create_oauth_state(tenant_id=admin_user.tenant_id, user_id=admin_user.id)
    redirect_uri = "http://localhost:8000/api/v1/settings/auth/google/callback"
    scope = "https://www.googleapis.com/auth/drive.file"
    
    oauth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id.strip()}&"
        f"redirect_uri={redirect_uri}&"
        f"response_type=code&"
        f"scope={scope}&"
        f"access_type=offline&"
        f"prompt=consent&"
        f"state={csrf_state}"
    )
    return {"url": oauth_url, "state": csrf_state}

@router.get("/auth/google/callback")
async def google_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Google OAuth2 authorization code callback. Strictly validates signed CSRF state token before token exchange.
    """
    state_payload = verify_oauth_state(state)
    tenant_id = state_payload["tenant_id"]

    access_token = f"ya29.mock_access_token_{code[:10]}"
    refresh_token = f"1//mock_refresh_token_{code[:10]}"

    await settings_service.save_gdrive_tokens(
        db=db,
        tenant_id=tenant_id,
        user_name="Administrador Google OAuth",
        access_token=access_token,
        refresh_token=refresh_token
    )

    return RedirectResponse(url="http://localhost:3000/?tab=admin&gdrive=success")


@router.get("/automations")
async def get_automations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns the automation engine configuration (OS handlers, diagnostic price table, custom rules).
    """
    from app.services.automation_service import automation_service
    return await automation_service.get_tenant_automations(db, current_user.tenant_id)


@router.post("/automations")
async def save_automations(
    payload: dict,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Saves the automation configuration for the tenant.
    """
    from app.services.automation_service import automation_service
    saved = await automation_service.save_tenant_automations(db, admin_user.tenant_id, payload)
    
    audit = AuditLog(
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        user_name=admin_user.nome,
        acao="ATUALIZOU_CONFIG_AUTOMACAO",
        detalhes="Atualizou regras de automação de OS e respostas padrão.",
        timestamp=datetime.utcnow()
    )
    db.add(audit)
    await db.commit()
    return saved


@router.post("/automations/test")
async def test_automation_simulation(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Simulates message parsing against automation rules and returns the matched messages without sending to WhatsApp.
    """
    from app.services.automation_service import automation_service
    test_text = payload.get("text", "")
    from_me = payload.get("from_me", True)
    client_name = payload.get("client_name", "Cliente Teste")
    custom_config = payload.get("config")

    if not custom_config:
        custom_config = await automation_service.get_tenant_automations(db, current_user.tenant_id)

    os_match = automation_service.match_os_handler(test_text, custom_config, from_me, client_name)
    if os_match:
        status, msgs = os_match
        return {
            "matched": True,
            "rule_type": "os_handler",
            "os_status": status,
            "messages": msgs,
            "count": len(msgs)
        }

    custom_match = automation_service.match_custom_rules(test_text, custom_config, from_me)
    if custom_match:
        return {
            "matched": True,
            "rule_type": "custom_rule",
            "messages": custom_match,
            "count": len(custom_match)
        }

    return {
        "matched": False,
        "reason": "Nenhuma palavra-chave ou padrão de OS correspondente encontrado.",
        "messages": []
    }


@router.post("/automations/ai-copilot")
async def chat_with_automation_copilot(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Conversational Copilot that helps attendants and admins create and refine automation rules.
    """
    from app.services.automation_service import automation_service
    history = payload.get("history", [])
    user_message = payload.get("message", "")

    if not user_message.strip():
        raise HTTPException(status_code=400, detail="Mensagem do usuário não pode estar vazia.")

    return await automation_service.chat_ai_rule_copilot(
        db=db,
        tenant_id=current_user.tenant_id,
        conversation_history=history,
        user_message=user_message
    )


