import os
import json
import logging
import asyncio
from typing import Optional, Dict, Any
import httpx
import asyncpg
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Contact

logger = logging.getLogger("lid_resolver_service")

PG_CONN_STR = "postgresql://omini_user:omini_password@172.18.0.2:5432/omini_db"

_LID_CACHE: Dict[str, Dict[str, Any]] = {}
_PG_POOL: Optional[asyncpg.Pool] = None

async def get_pg_pool() -> Optional[asyncpg.Pool]:
    global _PG_POOL
    if _PG_POOL is None or _PG_POOL._closed:
        try:
            _PG_POOL = await asyncpg.create_pool(PG_CONN_STR, min_size=1, max_size=5, timeout=3.0)
        except Exception as e:
            logger.debug(f"Could not connect directly to omini_postgres at 172.18.0.2: {e}")
            _PG_POOL = None
    return _PG_POOL

async def resolve_lid_info(lid_str: str) -> Dict[str, Any]:
    """
    Given any WhatsApp LID (e.g. '198440541790321' or '198440541790321@lid'),
    resolves:
      - real_phone: e.g. '556198334833'
      - name: e.g. 'Fernando Aragão'
      - profile_pic: e.g. 'https://pps.whatsapp.net/...'
    """
    clean_lid = str(lid_str).split("@")[0].strip()
    if not clean_lid:
        return {"lid": "", "real_phone": None, "name": None, "profile_pic": None}

    if clean_lid in _LID_CACHE:
        return _LID_CACHE[clean_lid]

    lid_jid = f"{clean_lid}@lid"

    real_phone = None
    name = None
    profile_pic = None

    pool = await get_pg_pool()
    if pool:
        try:
            async with pool.acquire() as conn:
                # 1. Check Contact table
                c_row = await conn.fetchrow('SELECT "pushName", "profilePicUrl" FROM "Contact" WHERE "remoteJid" = $1', lid_jid)
                if c_row:
                    if c_row["pushName"] and c_row["pushName"].strip() and c_row["pushName"] != clean_lid:
                        name = c_row["pushName"].strip()
                    if c_row["profilePicUrl"] and c_row["profilePicUrl"].strip():
                        profile_pic = c_row["profilePicUrl"].strip()

                # 2. Check Message table for remoteJidAlt
                msg_rows = await conn.fetch(
                    'SELECT "key", "pushName" FROM "Message" WHERE "key"::text LIKE $1 ORDER BY "id" DESC LIMIT 15',
                    f"%{clean_lid}%"
                )
                for m in msg_rows:
                    k = m["key"]
                    if isinstance(k, str):
                        try:
                            k = json.loads(k)
                        except Exception:
                            pass
                    if isinstance(k, dict):
                        alt = k.get("remoteJidAlt", "")
                        if "@s.whatsapp.net" in alt:
                            real_phone = alt.split("@")[0]
                            break
                    pname = m.get("pushName")
                    if pname and not name and pname not in ["Você", clean_lid, "Cliente"]:
                        name = pname

    # Fallback to docker exec if asyncpg couldn't connect
    if not real_phone:
        try:
            import subprocess
            sql = f"""
            SELECT 
                (SELECT "key"->>'remoteJidAlt' FROM "Message" WHERE "key"::text LIKE '%{clean_lid}%' AND "key"->>'remoteJidAlt' LIKE '%@s.whatsapp.net' LIMIT 1),
                (SELECT "pushName" FROM "Contact" WHERE "remoteJid" = '{lid_jid}' LIMIT 1),
                (SELECT "profilePicUrl" FROM "Contact" WHERE "remoteJid" = '{lid_jid}' LIMIT 1);
            """
            cmd = ["docker", "exec", "-i", "omini_postgres", "psql", "-U", "omini_user", "-d", "omini_db", "-t", "-A", "-F", "|||", "-c", sql]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.5)
            out = res.stdout.strip()
            if out and "|||" in out:
                parts = out.split("|||")
                if len(parts) >= 1 and parts[0] and "@s.whatsapp.net" in parts[0]:
                    real_phone = parts[0].split("@")[0]
                if len(parts) >= 2 and parts[1] and not name:
                    name = parts[1]
                if len(parts) >= 3 and parts[2] and not profile_pic:
                    profile_pic = parts[2]
        except Exception:
            pass

    info_res = {
        "lid": clean_lid,
        "real_phone": real_phone,
        "name": name,
        "profile_pic": profile_pic
    }
    _LID_CACHE[clean_lid] = info_res
    return info_res

async def download_and_cache_avatar_locally(contact_id: int, photo_url: Optional[str]) -> Optional[str]:
    """
    Downloads WhatsApp profile picture from remote URL (pps.whatsapp.net) and saves it
    permanently to local storage ('uploads/avatars/contact_{id}.jpg') so it never expires.
    """
    if not photo_url:
        return None
    if photo_url.startswith("/uploads/avatars/"):
        return photo_url

    avatars_dir = os.path.join("uploads", "avatars")
    os.makedirs(avatars_dir, exist_ok=True)
    target_filename = f"contact_{contact_id}.jpg"
    target_path = os.path.join(avatars_dir, target_filename)

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = await client.get(photo_url, headers=headers)
            if resp.status_code == 200 and len(resp.content) > 100:
                with open(target_path, "wb") as f:
                    f.write(resp.content)
                local_url = f"/uploads/avatars/{target_filename}"
                logger.info(f"Avatar for contact #{contact_id} cached permanently: {local_url}")

                try:
                    from app.core.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as db:
                        c_obj = await db.get(Contact, contact_id)
                        if c_obj:
                            c_obj.foto_perfil_url = local_url
                            await db.commit()
                except Exception:
                    pass

                return local_url
    except Exception as e:
        logger.debug(f"Failed to cache avatar locally for contact #{contact_id}: {e}")

    return None

async def resolve_and_bind_contact(
    session: AsyncSession,
    tenant_id: int,
    raw_jid: str,
    push_name: Optional[str] = None,
    profile_pic_url: Optional[str] = None,
    remote_jid_alt: Optional[str] = None
) -> Contact:
    """
    Given an incoming or synced JID (LID, group, or standard phone JID):
    1. Resolves LIDs into real phone numbers, names, and avatars.
    2. Searches existing contacts to prevent duplicates.
    3. Caches the avatar locally as a permanent .jpg in the background without blocking.
    4. Returns the clean, definitive Contact model instance.
    """
    clean_digits = "".join(filter(str.isdigit, raw_jid.split("@")[0]))
    is_lid = "@lid" in raw_jid or (len(clean_digits) >= 14 and not clean_digits.startswith("55") and not clean_digits.startswith("120363"))
    is_group = "@g.us" in raw_jid or clean_digits.startswith("120363")

    real_phone = clean_digits
    resolved_name = push_name
    resolved_pic = profile_pic_url

    # Check remote_jid_alt first if provided
    if remote_jid_alt and "@s.whatsapp.net" in str(remote_jid_alt):
        alt_digits = "".join(filter(str.isdigit, str(remote_jid_alt).split("@")[0]))
        if alt_digits.startswith("55") and len(alt_digits) in [12, 13]:
            real_phone = alt_digits

    if is_lid and not real_phone.startswith("55"):
        lid_res = await resolve_lid_info(clean_digits)
        if lid_res.get("real_phone"):
            real_phone = lid_res["real_phone"]
        if lid_res.get("name") and (not resolved_name or resolved_name in ["Cliente WhatsApp", clean_digits, "Cliente"]):
            resolved_name = lid_res["name"]
        if lid_res.get("profile_pic") and not resolved_pic:
            resolved_pic = lid_res["profile_pic"]

    # Deduplicate against existing contacts in the tenant
    contact = None
    if is_group:
        stmt = select(Contact).where(
            Contact.tenant_id == tenant_id,
            (Contact.telefone == raw_jid) | (Contact.telefone == clean_digits) | (Contact.telefone == f"{clean_digits}@g.us")
        )
        contact = (await session.execute(stmt)).scalars().first()
    else:
        # Match by exact phone or last 8 digits of real phone, OR match by LID stored in dados_adicionais
        conditions = []
        if real_phone and real_phone.startswith("55"):
            conditions.append(Contact.telefone == real_phone)
            if len(real_phone) >= 8:
                conditions.append(Contact.telefone.like(f"%{real_phone[-8:]}%"))
        else:
            conditions.append(Contact.telefone == real_phone)

        if is_lid and clean_digits:
            conditions.append(Contact.dados_adicionais.like(f'%"{clean_digits}"%'))

        stmt = select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.telefone.notlike("%@g.us%"),
            Contact.telefone.notlike("%-%"),
            Contact.telefone.notlike("120363%"),
            or_(*conditions)
        )
        contact = (await session.execute(stmt)).scalars().first()

    if not contact:
        clean_initial_name = resolved_name or (real_phone if real_phone.startswith("55") else "Cliente")
        extra_data = {}
        if is_group:
            extra_data["is_group"] = True
        if is_lid:
            extra_data["lid"] = clean_digits

        contact = Contact(
            tenant_id=tenant_id,
            telefone=real_phone,
            nome=clean_initial_name,
            foto_perfil_url=resolved_pic,
            dados_adicionais=extra_data
        )
        session.add(contact)
        await session.flush()
    else:
        # Update existing contact if better name or phone resolved
        if resolved_name and resolved_name not in ["Cliente", "Cliente WhatsApp", clean_digits, real_phone]:
            if contact.nome in ["Cliente", "Cliente WhatsApp", contact.telefone, clean_digits]:
                contact.nome = resolved_name
        if contact.telefone != real_phone and real_phone.startswith("55") and not contact.telefone.startswith("55"):
            contact.telefone = real_phone
        if is_lid:
            c_extra = contact.dados_adicionais or {}
            if not isinstance(c_extra, dict):
                try:
                    c_extra = json.loads(c_extra) if isinstance(c_extra, str) else {}
                except Exception:
                    c_extra = {}
            if c_extra.get("lid") != clean_digits:
                c_extra["lid"] = clean_digits
                contact.dados_adicionais = c_extra
        if resolved_pic and not contact.foto_perfil_url:
            contact.foto_perfil_url = resolved_pic

    # Non-blocking background avatar caching so DB transactions complete instantly
    target_pic = resolved_pic or profile_pic_url or contact.foto_perfil_url
    if target_pic and not target_pic.startswith("/uploads/avatars/"):
        asyncio.create_task(download_and_cache_avatar_locally(contact.id, target_pic))

    return contact
