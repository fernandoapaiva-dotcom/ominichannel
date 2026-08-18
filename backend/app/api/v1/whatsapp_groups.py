import logging
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.models import User, WhatsAppNumber, WhatsAppGroup, AuditLog
from app.api.v1.auth import get_current_user
from app.services.evolution_service import evolution_service

logger = logging.getLogger("whatsapp_groups")
router = APIRouter(prefix="/whatsapp-groups", tags=["WhatsApp Groups Management"])

@router.get("/", response_model=List[Dict[str, Any]])
async def list_whatsapp_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Lists all WhatsApp Groups for the current user's tenant.
    """
    stmt = (
        select(WhatsAppGroup)
        .options(selectinload(WhatsAppGroup.whatsapp_number))
        .where(WhatsAppGroup.tenant_id == current_user.tenant_id)
        .order_by(WhatsAppGroup.nome.asc())
    )
    res = await db.execute(stmt)
    groups = res.scalars().all()

    result = []
    for g in groups:
        result.append({
            "id": g.id,
            "tenant_id": g.tenant_id,
            "whatsapp_number_id": g.whatsapp_number_id,
            "group_jid": g.group_jid,
            "nome": g.nome,
            "ia_ativa": g.ia_ativa,
            "criado_em": g.criado_em.isoformat() if g.criado_em else None,
            "departamento": g.whatsapp_number.nome_departamento if g.whatsapp_number else "Desconhecido",
            "instancia": g.whatsapp_number.instancia_evolution_api if g.whatsapp_number else "",
            "numero": g.whatsapp_number.numero if g.whatsapp_number else ""
        })

    return result

@router.post("/sync")
async def sync_whatsapp_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Scans and syncs all WhatsApp groups from all active Evolution API instances for this tenant.
    New groups default to ia_ativa = False.
    """
    wn_stmt = select(WhatsAppNumber).where(
        WhatsAppNumber.tenant_id == current_user.tenant_id,
        WhatsAppNumber.status == True,
        WhatsAppNumber.provider_type == "evolution"
    )
    wn_res = await db.execute(wn_stmt)
    active_numbers = wn_res.scalars().all()

    if not active_numbers:
        return {"success": True, "synced_count": 0, "message": "Nenhum número ativo da Evolution API encontrado."}

    total_synced = 0

    for num in active_numbers:
        if not num.instancia_evolution_api:
            continue

        groups_raw = await evolution_service.fetch_all_groups(num.instancia_evolution_api)
        for g_data in groups_raw:
            if not isinstance(g_data, dict):
                continue

            group_jid = g_data.get("id") or g_data.get("jid")
            if not group_jid or not str(group_jid).endswith("@g.us"):
                continue

            subject = g_data.get("subject") or g_data.get("name") or g_data.get("subjectOwner") or f"Grupo {group_jid[:8]}"

            # Check existing group in DB
            g_stmt = select(WhatsAppGroup).where(
                WhatsAppGroup.tenant_id == current_user.tenant_id,
                WhatsAppGroup.whatsapp_number_id == num.id,
                WhatsAppGroup.group_jid == group_jid
            )
            g_res = await db.execute(g_stmt)
            existing_group = g_res.scalar_one_or_none()

            if existing_group:
                existing_group.nome = subject
            else:
                new_group = WhatsAppGroup(
                    tenant_id=current_user.tenant_id,
                    whatsapp_number_id=num.id,
                    group_jid=group_jid,
                    nome=subject,
                    ia_ativa=False # Disabled by default
                )
                db.add(new_group)

            total_synced += 1

    await db.commit()

    # Log audit
    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        user_name=current_user.nome,
        acao="SYNC_WHATSAPP_GROUPS",
        detalhes=f"Sincronização de grupos concluída. {total_synced} grupos processados."
    )
    db.add(audit)
    await db.commit()

    return {
        "success": True,
        "synced_count": total_synced,
        "message": f"{total_synced} grupos sincronizados com sucesso."
    }

@router.put("/{group_id}/toggle-ia")
async def toggle_group_ia(
    group_id: int,
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Toggles AI activation (ia_ativa) for a specific WhatsApp Group.
    """
    stmt = select(WhatsAppGroup).where(
        WhatsAppGroup.id == group_id,
        WhatsAppGroup.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    group = res.scalar_one_or_none()

    if not group:
        raise HTTPException(status_code=404, detail="Grupo do WhatsApp não encontrado.")

    ia_ativa = payload.get("ia_ativa")
    if ia_ativa is None:
        group.ia_ativa = not group.ia_ativa
    else:
        group.ia_ativa = bool(ia_ativa)

    await db.commit()
    await db.refresh(group)

    status_str = "ATIVADA" if group.ia_ativa else "DESATIVADA"
    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        user_name=current_user.nome,
        acao="TOGGLE_GROUP_IA",
        detalhes=f"Interação da IA {status_str} para o grupo '{group.nome}' ({group.group_jid})."
    )
    db.add(audit)
    await db.commit()

    return {
        "id": group.id,
        "nome": group.nome,
        "group_jid": group.group_jid,
        "ia_ativa": group.ia_ativa,
        "message": f"IA {status_str} com sucesso para o grupo '{group.nome}'."
    }
