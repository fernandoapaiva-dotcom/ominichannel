import json
import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger("gdrive_service")

class GDriveBackupService:
    def export_conversation_to_json(self, conversation_data: Dict[str, Any]) -> str:
        """Serializes conversation and messages into compact JSON string"""
        return json.dumps(conversation_data, ensure_ascii=False, separators=(',', ':'), default=str)

    def _get_drive_service_from_refresh_token(self, client_id: str, client_secret: str, refresh_token: str):
        """Builds an authenticated Google Drive service using OAuth refresh token."""
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
                token_uri="https://oauth2.googleapis.com/token",
                scopes=["https://www.googleapis.com/auth/drive.file"]
            )
            # Refresh to get a fresh access token
            creds.refresh(Request())
            service = build('drive', 'v3', credentials=creds)
            return service
        except Exception as e:
            logger.error(f"Erro ao autenticar no Google Drive via refresh token: {e}")
            return None

    async def sync_conversation_to_drive(
        self,
        tenant_drive_folder_id: str,
        conversation_id: int,
        contact_phone: str,
        conversation_data: Dict[str, Any],
        access_token: str = None,
        refresh_token: str = None,
        client_id: str = None,
        client_secret: str = None,
    ) -> bool:
        """
        Saves conversation as compact .json in backups_json/ and uploads to Google Drive
        using OAuth refresh token (never expires, no manual login needed).
        """
        try:
            # 1. Save locally first (always)
            backup_dir = os.path.join(os.getcwd(), "backups_json")
            os.makedirs(backup_dir, exist_ok=True)

            safe_phone = str(contact_phone).replace("+", "").replace(" ", "")
            filename = f"chat_{conversation_id}_{safe_phone}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = os.path.join(backup_dir, filename)

            json_content = self.export_conversation_to_json(conversation_data)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(json_content)

            logger.info(f"Backup local criado: {filepath} ({len(json_content)} bytes)")

            # 2. Upload to Google Drive if credentials are available
            if not tenant_drive_folder_id:
                logger.warning("ID da pasta do Drive não configurado. Apenas backup local realizado.")
                return True

            if not refresh_token or not client_id or not client_secret:
                logger.warning("Credenciais OAuth não configuradas. Apenas backup local realizado.")
                return True

            drive_service = self._get_drive_service_from_refresh_token(client_id, client_secret, refresh_token)
            if not drive_service:
                return False

            from googleapiclient.http import MediaFileUpload

            file_metadata = {
                'name': filename,
                'parents': [tenant_drive_folder_id]
            }

            media = MediaFileUpload(filepath, mimetype='application/json', resumable=False)

            uploaded_file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,name'
            ).execute()

            logger.info(f"✅ Upload no Google Drive concluído! Arquivo: '{uploaded_file.get('name')}' | ID: {uploaded_file.get('id')}")
            return True

        except Exception as e:
            logger.error(f"Erro no backup do Google Drive para conversa {conversation_id}: {e}")
            return False


gdrive_service = GDriveBackupService()
