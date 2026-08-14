import asyncio
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_admin_user, get_current_user, encrypt_data, decrypt_data, mask_sensitive_string
from app.models.models import WhatsAppNumber, User, user_number_access
from app.schemas.schemas import WhatsAppNumberCreate, WhatsAppNumberResponse

router = APIRouter(prefix="/whatsapp-numbers", tags=["WhatsApp Numbers & Departments"])

def _to_response_schema(wn: WhatsAppNumber) -> WhatsAppNumberResponse:
    decrypted_token = decrypt_data(wn.meta_access_token_encrypted) if wn.meta_access_token_encrypted else ""
    return WhatsAppNumberResponse(
        id=wn.id,
        tenant_id=wn.tenant_id,
        provider_type=wn.provider_type or "evolution",
        numero=wn.numero,
        nome_departamento=wn.nome_departamento,
        instancia_evolution_api=wn.instancia_evolution_api,
        meta_phone_number_id=wn.meta_phone_number_id,
        meta_waba_id=wn.meta_waba_id,
        meta_access_token_masked=mask_sensitive_string(decrypted_token) if decrypted_token else None,
        status=wn.status
    )

@router.get("/", response_model=List[WhatsAppNumberResponse])
async def list_accessible_whatsapp_numbers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role == "admin":
        stmt = select(WhatsAppNumber).where(WhatsAppNumber.tenant_id == current_user.tenant_id)
    else:
        stmt = (
            select(WhatsAppNumber)
            .join(user_number_access)
            .where(
                WhatsAppNumber.tenant_id == current_user.tenant_id,
                user_number_access.c.user_id == current_user.id
            )
        )
    result = await db.execute(stmt)
    numbers = result.scalars().all()
    return [_to_response_schema(wn) for wn in numbers]

@router.post("/", response_model=WhatsAppNumberResponse, status_code=status.HTTP_201_CREATED)
async def create_whatsapp_number(
    wn_in: WhatsAppNumberCreate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    if wn_in.provider_type == "meta" and (not wn_in.meta_access_token or not wn_in.meta_access_token.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O Access Token da Meta é obrigatório para cadastrar uma conexão WhatsApp Oficial."
        )

    encrypted_token = encrypt_data(wn_in.meta_access_token.strip()) if (wn_in.meta_access_token and wn_in.meta_access_token.strip()) else None
    
    wn = WhatsAppNumber(
        tenant_id=admin_user.tenant_id,
        provider_type=wn_in.provider_type or "evolution",
        numero=wn_in.numero,
        nome_departamento=wn_in.nome_departamento,
        instancia_evolution_api=wn_in.instancia_evolution_api if wn_in.provider_type != "meta" else None,
        meta_phone_number_id=wn_in.meta_phone_number_id if wn_in.provider_type == "meta" else None,
        meta_waba_id=wn_in.meta_waba_id if wn_in.provider_type == "meta" else None,
        meta_access_token_encrypted=encrypted_token if wn_in.provider_type == "meta" else None,
        status=wn_in.status
    )
    db.add(wn)
    await db.commit()
    await db.refresh(wn)
    return _to_response_schema(wn)

@router.put("/{number_id}", response_model=WhatsAppNumberResponse)
async def update_whatsapp_number(
    number_id: int,
    wn_in: WhatsAppNumberCreate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(WhatsAppNumber).where(
        WhatsAppNumber.id == number_id,
        WhatsAppNumber.tenant_id == admin_user.tenant_id
    )
    res = await db.execute(stmt)
    wn = res.scalar_one_or_none()
    if not wn:
        raise HTTPException(status_code=404, detail="Número de WhatsApp / Departamento não encontrado")

    if wn_in.provider_type == "meta":
        has_existing_token = bool(wn.meta_access_token_encrypted)
        has_new_token = bool(wn_in.meta_access_token and wn_in.meta_access_token.strip())
        if not has_existing_token and not has_new_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O Access Token da Meta é obrigatório para cadastrar uma conexão WhatsApp Oficial."
            )

    wn.provider_type = wn_in.provider_type or "evolution"
    wn.nome_departamento = wn_in.nome_departamento
    wn.numero = wn_in.numero
    wn.status = wn_in.status

    if wn_in.provider_type == "meta":
        wn.meta_phone_number_id = wn_in.meta_phone_number_id
        wn.meta_waba_id = wn_in.meta_waba_id
        if wn_in.meta_access_token and wn_in.meta_access_token.strip():
            wn.meta_access_token_encrypted = encrypt_data(wn_in.meta_access_token.strip())
        wn.instancia_evolution_api = None
    else:
        wn.instancia_evolution_api = wn_in.instancia_evolution_api
        wn.meta_phone_number_id = None
        wn.meta_waba_id = None
        wn.meta_access_token_encrypted = None

    await db.commit()
    await db.refresh(wn)
    return _to_response_schema(wn)

@router.delete("/{number_id}", status_code=status.HTTP_200_OK)
async def delete_whatsapp_number(
    number_id: int,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(WhatsAppNumber).where(
        WhatsAppNumber.id == number_id,
        WhatsAppNumber.tenant_id == admin_user.tenant_id
    )
    res = await db.execute(stmt)
    wn = res.scalar_one_or_none()
    if not wn:
        raise HTTPException(status_code=404, detail="Número de WhatsApp / Departamento não encontrado")

    await db.delete(wn)
    await db.commit()
    return {"status": "success", "message": "Número de WhatsApp removido com sucesso"}

@router.get("/{number_id}/qrcode")
async def get_number_qrcode(
    number_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(WhatsAppNumber).where(
        WhatsAppNumber.id == number_id,
        WhatsAppNumber.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    wn = res.scalar_one_or_none()
    if not wn:
        raise HTTPException(status_code=404, detail="Número de WhatsApp não encontrado")

    if (wn.provider_type or "evolution") != "evolution":
        raise HTTPException(status_code=400, detail="Conexão via QR Code disponível apenas para o provedor Evolution API.")

    instance = wn.instancia_evolution_api or wn.numero or f"instancia_{wn.id}"
    
    from app.services.settings_service import settings_service
    from app.services.evolution_service import evolution_service
    decrypted = await settings_service.get_tenant_decrypted_settings(db, current_user.tenant_id)
    
    # 1. Check in-memory webhook QR cache first
    qrcode_base64 = evolution_service.qr_code_cache.get(instance)

    # 2. Check connectionState / existence on Evolution API
    if not qrcode_base64:
        conn_state = await evolution_service.get_connection_state(
            instance_name=instance,
            custom_base_url=decrypted.get("evolution_api_url"),
            custom_api_key=decrypted.get("evolution_api_key")
        )
        
        instance_exists = True
        if isinstance(conn_state, dict):
            if conn_state.get("status") == 404:
                instance_exists = False
            elif isinstance(conn_state.get("response"), dict) and "does not exist" in str(conn_state.get("response", {}).get("message", "")).lower():
                instance_exists = False

        if not instance_exists:
            # Create instance fresh ONLY if it does not exist on Evolution API
            await evolution_service.create_instance(
                instance_name=instance,
                custom_base_url=decrypted.get("evolution_api_url"),
                custom_api_key=decrypted.get("evolution_api_key")
            )
            await asyncio.sleep(2.0)

    # 3. Poll connect endpoint & webhook cache up to 20 attempts (2.0s delay = 40 seconds max)
    evo_res = {}
    if not qrcode_base64:
        for attempt in range(20):
            # Check webhook cache first
            if instance in evolution_service.qr_code_cache:
                qrcode_base64 = evolution_service.qr_code_cache[instance]
                break

            evo_res = await evolution_service.get_qr_code(
                instance_name=instance,
                custom_base_url=decrypted.get("evolution_api_url"),
                custom_api_key=decrypted.get("evolution_api_key")
            )
            if isinstance(evo_res, dict):
                if "base64" in evo_res:
                    qrcode_base64 = evo_res.get("base64")
                elif "code" in evo_res:
                    qrcode_base64 = evo_res.get("code")
                elif "qrcode" in evo_res and isinstance(evo_res["qrcode"], dict):
                    qrcode_base64 = evo_res["qrcode"].get("base64")

            if qrcode_base64:
                evolution_service.qr_code_cache[instance] = qrcode_base64
                break

            await asyncio.sleep(2.0)
    
    pairing_code = evo_res.get("pairingCode") if isinstance(evo_res, dict) else None
    state = "DISCONNECTED"
    if isinstance(evo_res, dict):
        instance_data = evo_res.get("instance", {})
        if isinstance(instance_data, dict):
            state = instance_data.get("state", "DISCONNECTED")

    # Extract any error message if QR code is still missing
    error_msg = None
    if not qrcode_base64:
        if isinstance(evo_res, dict):
            if "error" in evo_res:
                error_msg = str(evo_res.get("error"))
            elif "response" in evo_res and isinstance(evo_res["response"], dict):
                error_msg = str(evo_res["response"].get("message"))
            elif evo_res.get("count") == 0:
                error_msg = f"A instância '{instance}' na Evolution API ainda não gerou o par de chaves WhatsApp. Clique em reconectar ou aguarde o ciclo do servidor."
        if not error_msg:
            error_msg = "Aguardando inicialização do QR Code pela Evolution API..."

    return {
        "number_id": wn.id,
        "instancia": instance,
        "qrcode": qrcode_base64,
        "pairing_code": pairing_code,
        "state": state,
        "error": error_msg,
        "raw_response": evo_res
    }

@router.get("/{number_id}/connection-status")
async def get_number_connection_status(
    number_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(WhatsAppNumber).where(
        WhatsAppNumber.id == number_id,
        WhatsAppNumber.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    wn = res.scalar_one_or_none()
    if not wn:
        raise HTTPException(status_code=404, detail="Número de WhatsApp não encontrado")

    if (wn.provider_type or "evolution") != "evolution":
        return {
            "number_id": wn.id,
            "provider_type": "meta",
            "connected": True,
            "state": "open"
        }

    instance = wn.instancia_evolution_api or wn.numero or f"instancia_{wn.id}"
    
    from app.services.settings_service import settings_service
    from app.services.evolution_service import evolution_service
    decrypted = await settings_service.get_tenant_decrypted_settings(db, current_user.tenant_id)
    
    evo_res = await evolution_service.get_connection_state(
        instance_name=instance,
        custom_base_url=decrypted.get("evolution_api_url"),
        custom_api_key=decrypted.get("evolution_api_key")
    )
    
    state = "close"
    if isinstance(evo_res, dict):
        instance_data = evo_res.get("instance", {})
        if isinstance(instance_data, dict):
            state = instance_data.get("state", "close")
        elif "state" in evo_res:
            state = evo_res.get("state", "close")

    connected = state in ["open", "connected"]

    return {
        "number_id": wn.id,
        "provider_type": "evolution",
        "instancia": instance,
        "connected": connected,
        "state": state,
        "raw_response": evo_res
    }
