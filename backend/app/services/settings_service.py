import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import IntegrationSettings, AuditLog, User
from app.core.security import encrypt_data, decrypt_data, mask_sensitive_string
from app.core.config import settings as env_settings

logger = logging.getLogger("settings_service")

class SettingsService:
    async def get_tenant_decrypted_settings(self, db: AsyncSession, tenant_id: int) -> Dict[str, Any]:
        """
        Retrieves and decrypts tenant settings from DB.
        Falls back to 'gemini-3.1-flash-lite' default if model is not specified.
        """
        stmt = select(IntegrationSettings).where(IntegrationSettings.tenant_id == tenant_id)
        result = await db.execute(stmt)
        records = result.scalars().all()
        
        settings_map: Dict[str, Dict[str, Any]] = {}
        for rec in records:
            decrypted_json_str = decrypt_data(rec.encrypted_payload)
            if decrypted_json_str:
                try:
                    settings_map[rec.integration_type] = json.loads(decrypted_json_str)
                except Exception:
                    pass

        gemini_data = settings_map.get("gemini", {})
        evolution_data = settings_map.get("evolution", {})
        general_data = settings_map.get("general", {})
        gdrive_data = settings_map.get("gdrive", {})

        evo_key = evolution_data.get("evolution_api_key", "")
        if not evo_key or evo_key in ["omini_master_key_123", "Nova Master Key", "Master Key"]:
            evo_key = env_settings.EVOLUTION_API_KEY or "omini_master_key_123"

        gemini_model = gemini_data.get("gemini_model_name") or "gemini-2.5-flash"


        return {
            "gemini_api_key": gemini_data.get("gemini_api_key") or env_settings.GEMINI_API_KEY,
            "gemini_model_name": gemini_model,
            "evolution_api_url": evolution_data.get("evolution_api_url") or env_settings.EVOLUTION_API_URL,
            "evolution_api_key": evo_key,
            "inatividade_minutos": general_data.get("inatividade_minutos", 30),
            "gdrive_access_token": gdrive_data.get("access_token", ""),
            "gdrive_refresh_token": gdrive_data.get("refresh_token", ""),
            "gdrive_folder_id": gdrive_data.get("folder_id", ""),
            "google_client_id": gdrive_data.get("client_id") or os.environ.get("GOOGLE_CLIENT_ID", ""),
            "google_client_secret": gdrive_data.get("client_secret") or os.environ.get("GOOGLE_CLIENT_SECRET", "")
        }

    async def get_tenant_masked_settings(self, db: AsyncSession, tenant_id: int) -> Dict[str, Any]:
        decrypted = await self.get_tenant_decrypted_settings(db, tenant_id)
        return {
            "gemini_configured": bool(decrypted["gemini_api_key"]),
            "gemini_api_key_masked": mask_sensitive_string(decrypted["gemini_api_key"]),
            "gemini_model_name": decrypted["gemini_model_name"],
            "evolution_api_url": decrypted["evolution_api_url"],
            "evolution_api_key_masked": mask_sensitive_string(decrypted["evolution_api_key"]),
            "inatividade_minutos": decrypted["inatividade_minutos"],
            "google_drive_connected": bool(decrypted["gdrive_refresh_token"]),
            "google_drive_folder_id": decrypted["gdrive_folder_id"],
            "google_client_id": decrypted["google_client_id"],
            "google_client_secret_masked": mask_sensitive_string(decrypted["google_client_secret"])
        }

    async def save_tenant_integration_settings(
        self,
        db: AsyncSession,
        tenant_id: int,
        user: User,
        payload: Dict[str, Any]
    ) -> bool:
        # 1. Update Gemini
        if "gemini_api_key" in payload or "gemini_model_name" in payload:
            existing = await self.get_tenant_decrypted_settings(db, tenant_id)
            new_gemini_key = payload.get("gemini_api_key")
            final_gemini_key = new_gemini_key.strip() if (new_gemini_key and str(new_gemini_key).strip()) else existing["gemini_api_key"]
            raw_gemini = {
                "gemini_api_key": final_gemini_key,
                "gemini_model_name": payload.get("gemini_model_name") or existing["gemini_model_name"]
            }
            enc_gemini = encrypt_data(json.dumps(raw_gemini))
            await self._upsert_setting(db, tenant_id, "gemini", enc_gemini)

        # 2. Update Evolution API
        if "evolution_api_url" in payload or "evolution_api_key" in payload:
            existing = await self.get_tenant_decrypted_settings(db, tenant_id)
            new_evo_key = payload.get("evolution_api_key")
            final_evo_key = new_evo_key.strip() if (new_evo_key and str(new_evo_key).strip()) else existing["evolution_api_key"]
            raw_evo = {
                "evolution_api_url": payload.get("evolution_api_url") or existing["evolution_api_url"],
                "evolution_api_key": final_evo_key
            }
            enc_evo = encrypt_data(json.dumps(raw_evo))
            await self._upsert_setting(db, tenant_id, "evolution", enc_evo)

        # 3. Update General (Inactivity)
        if "inatividade_minutos" in payload:
            raw_gen = {"inatividade_minutos": payload["inatividade_minutos"]}
            enc_gen = encrypt_data(json.dumps(raw_gen))
            await self._upsert_setting(db, tenant_id, "general", enc_gen)

        # 4. Update Google Drive Settings
        if "google_drive_folder_id" in payload or "google_client_id" in payload or "google_client_secret" in payload:
            existing = await self.get_tenant_decrypted_settings(db, tenant_id)
            raw_gdrive = {
                "folder_id": payload.get("google_drive_folder_id") if "google_drive_folder_id" in payload else existing["gdrive_folder_id"],
                "client_id": payload.get("google_client_id") if "google_client_id" in payload else existing["google_client_id"],
                "client_secret": payload.get("google_client_secret") if "google_client_secret" in payload else existing["google_client_secret"],
                "access_token": existing["gdrive_access_token"],
                "refresh_token": existing["gdrive_refresh_token"]
            }
            enc_gdrive = encrypt_data(json.dumps(raw_gdrive))
            await self._upsert_setting(db, tenant_id, "gdrive", enc_gdrive)

        audit = AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            user_name=user.nome,
            acao="ALTEROU_CONFIGURACOES_INTEGRACAO",
            detalhes=f"Usuário '{user.nome}' atualizou as configurações de integração do tenant.",
            timestamp=datetime.utcnow()
        )
        db.add(audit)
        await db.commit()
        return True

    async def save_gdrive_tokens(
        self,
        db: AsyncSession,
        tenant_id: int,
        user_name: str,
        access_token: str,
        refresh_token: str,
        folder_id: Optional[str] = None
    ):
        raw_gdrive = {
            "folder_id": folder_id or "",
            "access_token": access_token,
            "refresh_token": refresh_token
        }
        enc_gdrive = encrypt_data(json.dumps(raw_gdrive))
        await self._upsert_setting(db, tenant_id, "gdrive", enc_gdrive)

        audit = AuditLog(
            tenant_id=tenant_id,
            user_name=user_name,
            acao="CONECTOU_CONTA_GOOGLE_DRIVE",
            detalhes="Conta do Google Drive conectada via OAuth2 com sucesso.",
            timestamp=datetime.utcnow()
        )
        db.add(audit)
        await db.commit()

    async def _upsert_setting(self, db: AsyncSession, tenant_id: int, integration_type: str, encrypted_payload: str):
        stmt = select(IntegrationSettings).where(
            IntegrationSettings.tenant_id == tenant_id,
            IntegrationSettings.integration_type == integration_type
        )
        res = await db.execute(stmt)
        record = res.scalar_one_or_none()

        if record:
            record.encrypted_payload = encrypted_payload
            record.atualizado_em = datetime.utcnow()
        else:
            record = IntegrationSettings(
                tenant_id=tenant_id,
                integration_type=integration_type,
                encrypted_payload=encrypted_payload
            )
            db.add(record)

settings_service = SettingsService()
