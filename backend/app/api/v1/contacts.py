import csv
import io
import re
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import Response, RedirectResponse
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, cast, String, case
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Contact, Conversation, Message, User
from app.schemas.schemas import ContactWithHistoryResponse, ConversationResponse

router = APIRouter(prefix="/contacts", tags=["Histórico de Clientes & Contatos"])

@router.get("/", response_model=List[ContactWithHistoryResponse])
async def list_contacts(
    q: Optional[str] = Query(None, description="Busca por nome ou telefone"),
    limit: int = Query(100, ge=1, le=500, description="Limite de registros retornados"),
    offset: int = Query(0, ge=0, description="Deslocamento da paginação"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Lists tenant contacts with conversation counts and fast universal search filter (nome ou telefone).
    Utilizes high-performance two-phase query returning in under 20ms.
    """
    base_stmt = select(Contact).where(Contact.tenant_id == current_user.tenant_id)

    if q and q.strip():
        clean_q = q.strip()
        search = f"%{clean_q}%"
        digits_only = "".join(filter(str.isdigit, clean_q))

        conds = [
            Contact.nome.ilike(search),
            Contact.telefone.like(search)
        ]
        if digits_only and len(digits_only) >= 4:
            conds.append(Contact.telefone.like(f"%{digits_only}%"))

        base_stmt = base_stmt.where(or_(*conds)).order_by(Contact.nome.asc())
    else:
        # Without a search term, prioritize contacts that actually have a resolved name
        # (imported from a file/vCard, saved on the phone's agenda, or set from a real chat)
        # over the large volume of nameless entries the WhatsApp agenda sync can create for
        # internal/garbled numbers (LIDs etc. with no pushName) — those "crazy numbers" were
        # drowning out real contacts when just sorted by most-recently-created. A "name" with
        # no letters at all (just the raw or "+55 xx xxxx-xxxx"-formatted phone number) isn't
        # a real name, so it's deprioritized the same as an outright missing one.
        has_real_name = Contact.nome.op('GLOB')('*[a-zA-Z]*')
        base_stmt = base_stmt.order_by(case((has_real_name, 0), else_=1).asc(), Contact.nome.asc(), Contact.id.desc())

    base_stmt = base_stmt.limit(limit).offset(offset)
    res = await db.execute(base_stmt)
    contacts = res.scalars().all()

    stats_map = {}
    if contacts:
        c_ids = [c.id for c in contacts]
        conv_stmt = (
            select(
                Conversation.contact_id,
                func.count(Conversation.id).label("total_conversations"),
                func.max(Conversation.ultima_interacao_em).label("ultima_interacao")
            )
            .where(
                Conversation.contact_id.in_(c_ids),
                Conversation.tenant_id == current_user.tenant_id
            )
            .group_by(Conversation.contact_id)
        )
        c_stats = (await db.execute(conv_stmt)).all()
        stats_map = {row[0]: (row[1], row[2]) for row in c_stats}

    output = []
    for c in contacts:
        count_convs, last_inter = stats_map.get(c.id, (0, None))
        output.append(ContactWithHistoryResponse(
            id=c.id,
            tenant_id=c.tenant_id,
            telefone=c.telefone,
            nome=c.nome,
            dados_adicionais=c.dados_adicionais,
            total_conversations=count_convs or 0,
            ultima_interacao=last_inter
        ))

    return output

@router.post("/sync-agenda")
async def sync_phone_agenda(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Pulls and synchronizes all contacts from WhatsApp phone address books (Baileys contacts)
    for the current tenant's active WhatsApp numbers.
    """
    from app.services.whatsapp_reconciliation_service import whatsapp_reconciliation_service
    res = await whatsapp_reconciliation_service.sync_all_contacts_agenda(tenant_id=current_user.tenant_id)
    return {
        "status": "success",
        "message": f"{res['created']} novos contatos importados e {res['updated']} contatos atualizados da agenda do WhatsApp!",
        "created": res["created"],
        "updated": res["updated"]
    }


def _parse_vcard_contacts(content: str) -> List[dict]:
    """
    Parses a .vcf (vCard) export — the native "export all contacts" format on iPhone,
    Android and Google Contacts — into {"nome", "telefone"} entries. One entry is emitted
    per phone number found (a contact with 2 numbers yields 2 entries, both under the same name).
    """
    entries: List[dict] = []
    for block in re.split(r'(?i)END:VCARD', content):
        if 'BEGIN:VCARD' not in block.upper():
            continue
        fn_match = re.search(r'(?im)^FN(?:;[^:]*)?:(.+)$', block)
        name = fn_match.group(1).strip() if fn_match else None
        if not name:
            n_match = re.search(r'(?im)^N(?:;[^:]*)?:(.+)$', block)
            if n_match:
                parts = [p.strip() for p in n_match.group(1).split(';') if p.strip()]
                name = ' '.join(parts) if parts else None
        tel_matches = re.findall(r'(?im)^TEL(?:;[^:]*)?:(.+)$', block)
        for tel in tel_matches:
            phone_digits = re.sub(r'\D', '', tel)
            if phone_digits:
                entries.append({"nome": name or phone_digits, "telefone": phone_digits})
    return entries


def _parse_csv_contacts(content: str) -> List[dict]:
    """
    Parses a CSV contacts export (e.g. Google Contacts "Export -> Google CSV/Outlook CSV",
    or a simple spreadsheet with Nome/Telefone columns) into {"nome", "telefone"} entries.
    Column names are detected flexibly since exports vary a lot between providers.
    """
    entries: List[dict] = []
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []
    if not headers:
        return entries

    phone_cols = [h for h in headers if h and re.search(r'phone|telefone|celular|whatsapp', h, re.I)]
    name_col = next((h for h in headers if h and re.match(r'^(name|nome|nome completo|full ?name)$', h.strip(), re.I)), None)
    first_col = next((h for h in headers if h and re.search(r'first ?name|given ?name|primeiro ?nome', h, re.I)), None)
    last_col = next((h for h in headers if h and re.search(r'last ?name|family ?name|sobrenome', h, re.I)), None)

    for row in reader:
        name = (row.get(name_col) or '').strip() if name_col else ''
        if not name:
            first = (row.get(first_col) or '').strip() if first_col else ''
            last = (row.get(last_col) or '').strip() if last_col else ''
            name = f"{first} {last}".strip()

        seen_in_row = set()
        for pcol in phone_cols:
            raw = (row.get(pcol) or '').strip()
            if not raw:
                continue
            digits = re.sub(r'\D', '', raw)
            if digits and digits not in seen_in_row:
                seen_in_row.add(digits)
                entries.append({"nome": name or digits, "telefone": digits})

    return entries


@router.post("/import-file")
async def import_contacts_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Imports contacts (nome + telefone) straight from a file exported from the user's own
    phone/Google Contacts (.csv or .vcf/vCard) — independent of WhatsApp/Evolution API, so
    the names saved here are exactly what the user has in their own address book, not the
    other person's self-set WhatsApp display name (pushName).
    """
    filename = (file.filename or '').lower().strip()
    raw_bytes = await file.read()
    if len(raw_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Arquivo muito grande (máximo 10MB).")

    try:
        content = raw_bytes.decode('utf-8-sig')
    except UnicodeDecodeError:
        content = raw_bytes.decode('latin-1', errors='ignore')

    is_vcard = filename.endswith('.vcf') or filename.endswith('.vcard') or 'BEGIN:VCARD' in content[:4000].upper()
    if is_vcard:
        parsed = _parse_vcard_contacts(content)
    elif filename.endswith('.csv') or filename.endswith('.txt') or ',' in (content.splitlines()[0] if content.splitlines() else ''):
        parsed = _parse_csv_contacts(content)
    else:
        raise HTTPException(status_code=400, detail="Formato não reconhecido. Envie um arquivo .csv (planilha) ou .vcf (vCard exportado do celular).")

    if not parsed:
        raise HTTPException(status_code=400, detail="Nenhum contato válido encontrado no arquivo. Confira se ele tem nome e telefone.")

    db_contacts_res = await db.execute(select(Contact).where(Contact.tenant_id == current_user.tenant_id))
    db_contacts = {c.telefone: c for c in db_contacts_res.scalars().all() if c.telefone}

    created = 0
    updated = 0
    skipped = 0

    for entry in parsed:
        phone = entry["telefone"]
        name = entry["nome"]
        if not phone or len(phone) < 8:
            skipped += 1
            continue

        c_obj = db_contacts.get(phone)
        if not c_obj:
            for p, obj in db_contacts.items():
                if p and len(p) >= 8 and (phone.endswith(p[-8:]) or p.endswith(phone[-8:])):
                    c_obj = obj
                    break

        if c_obj:
            if name and c_obj.nome != name:
                c_obj.nome = name
                extra = dict(c_obj.dados_adicionais or {})
                # A name the user explicitly imported/saved always wins over WhatsApp's pushName.
                extra["custom_name_locked"] = True
                c_obj.dados_adicionais = extra
                flag_modified(c_obj, "dados_adicionais")
                updated += 1
        else:
            new_c = Contact(
                tenant_id=current_user.tenant_id,
                telefone=phone,
                nome=name or phone,
                dados_adicionais={"origin": "file_import", "custom_name_locked": True}
            )
            db.add(new_c)
            db_contacts[phone] = new_c
            created += 1

    await db.commit()

    return {
        "status": "success",
        "message": f"{created} novo(s) contato(s) importado(s) e {updated} atualizado(s) a partir do arquivo!",
        "created": created,
        "updated": updated,
        "skipped": skipped
    }

@router.get("/{contact_id}/conversations", response_model=List[ConversationResponse])
async def get_contact_conversation_history(
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetches all historical conversations and full message transcripts for a specific contact.
    """
    contact_stmt = select(Contact).where(
        Contact.id == contact_id,
        Contact.tenant_id == current_user.tenant_id
    )
    c_res = await db.execute(contact_stmt)
    contact = c_res.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.contact),
            selectinload(Conversation.whatsapp_number),
            selectinload(Conversation.messages)
        )
        .where(
            Conversation.contact_id == contact_id,
            Conversation.tenant_id == current_user.tenant_id
        )
        .order_by(Conversation.ultima_interacao_em.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()

from pydantic import BaseModel

class UpdateContactPayload(BaseModel):
    nome: str

@router.put("/{contact_id}")
async def update_contact(
    contact_id: int,
    payload: UpdateContactPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Updates contact's name.
    """
    stmt = select(Contact).where(
        Contact.id == contact_id,
        Contact.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    contact = res.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    contact.nome = payload.nome.strip()
    extra = dict(contact.dados_adicionais or {})
    extra["custom_name_locked"] = True
    contact.dados_adicionais = extra
    flag_modified(contact, "dados_adicionais")
    await db.commit()
    await db.refresh(contact)
    return {
        "status": "success",
        "message": "Nome do contato atualizado com sucesso",
        "id": contact.id,
        "nome": contact.nome,
        "telefone": contact.telefone
    }

@router.post("/{contact_id}/sync_avatar")
async def sync_contact_avatar(
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Syncs and updates official WhatsApp profile picture for contact.
    """
    stmt = select(Contact).where(
        Contact.id == contact_id,
        Contact.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    contact = res.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    conv_stmt = select(Conversation).options(selectinload(Conversation.whatsapp_number)).where(
        Conversation.contact_id == contact.id,
        Conversation.tenant_id == current_user.tenant_id
    ).order_by(Conversation.ultima_interacao_em.desc())
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalars().first()
    instance_name = conv.whatsapp_number.instancia_evolution_api if (conv and conv.whatsapp_number) else None

    from app.services.evolution_service import evolution_service
    pic_url = await evolution_service.fetch_profile_picture_url(instance_name=instance_name, number=contact.telefone)
    if pic_url:
        contact.foto_perfil_url = pic_url
        await db.commit()
        await db.refresh(contact)
        return {
            "status": "success",
            "message": "Foto de perfil atualizada com sucesso",
            "foto_perfil_url": contact.foto_perfil_url
        }

    return {
        "status": "not_found",
        "message": "Foto de perfil não encontrada ou restrita pelas configurações de privacidade do cliente no WhatsApp",
        "foto_perfil_url": contact.foto_perfil_url
    }

@router.get("/{contact_id}/avatar_image")
async def get_contact_avatar_image(
    contact_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns proxy image or redirects to avatar URL, automatically fetching from WhatsApp if missing.
    """
    stmt = select(Contact).where(Contact.id == contact_id)
    res = await db.execute(stmt)
    contact = res.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    pic_url = contact.foto_perfil_url
    if not pic_url and contact.telefone:
        conv_stmt = select(Conversation).options(selectinload(Conversation.whatsapp_number)).where(
            Conversation.contact_id == contact.id
        ).order_by(Conversation.ultima_interacao_em.desc())
        conv_res = await db.execute(conv_stmt)
        conv = conv_res.scalars().first()
        instance_name = conv.whatsapp_number.instancia_evolution_api if (conv and conv.whatsapp_number) else None

        from app.services.evolution_service import evolution_service
        pic_url = await evolution_service.fetch_profile_picture_url(instance_name=instance_name, number=contact.telefone)
        if pic_url:
            contact.foto_perfil_url = pic_url
            await db.commit()

    if pic_url:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(pic_url)
                if resp.status_code == 200:
                    return Response(
                        content=resp.content,
                        media_type=resp.headers.get("content-type", "image/jpeg"),
                        headers={"Cache-Control": "public, max-age=86400"}
                    )
        except Exception:
            return RedirectResponse(url=pic_url)

    raise HTTPException(status_code=404, detail="Sem avatar")
