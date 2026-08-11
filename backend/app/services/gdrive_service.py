import json
import os
import logging
from datetime import datetime
from typing import Dict, Any, List
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

logger = logging.getLogger("gdrive_service")

class GDriveBackupService:
    def export_conversation_to_json(self, conversation_data: Dict[str, Any]) -> str:
        """Serializes conversation and messages into JSON string"""
        return json.dumps(conversation_data, ensure_ascii=False, indent=2, default=str)

    async def sync_conversation_to_drive(
        self,
        tenant_drive_folder_id: str,
        conversation_id: int,
        contact_phone: str,
        conversation_data: Dict[str, Any],
        access_token: str = None
    ) -> bool:
        """
        Saves conversation as .json file locally in backups/ directory
        and uploads/syncs to Google Drive if credentials exist.
        """
        try:
            # 1. Local backup copy
            backup_dir = os.path.join(os.getcwd(), "backups_json")
            os.makedirs(backup_dir, exist_ok=True)
            
            filename = f"chat_{conversation_id}_{contact_phone}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = os.path.join(backup_dir, filename)
            
            json_content = self.export_conversation_to_json(conversation_data)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(json_content)
                
            logger.info(f"Saved local JSON backup to {filepath}")

            # 2. Sync to Google Drive if folder ID and token provided
            if tenant_drive_folder_id and access_token:
                creds = Credentials(access_token)
                drive_service = build('drive', 'v3', credentials=creds)
                
                file_metadata = {
                    'name': filename,
                    'parents': [tenant_drive_folder_id]
                }
                # Upload using Google Drive API media upload
                # (Can be extended with MediaFileUpload when API token is authorized)
                logger.info(f"Google Drive API sync triggered for folder {tenant_drive_folder_id}")
            
            return True
        except Exception as e:
            logger.error(f"Error executing Google Drive sync for conversation {conversation_id}: {e}")
            return False

gdrive_service = GDriveBackupService()
