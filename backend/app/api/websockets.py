import logging
from typing import Dict, List, Tuple
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
import jwt

from app.core.config import settings

logger = logging.getLogger("websockets")
router = APIRouter(tags=["WebSockets Realtime"])

class ConnectionManager:
    def __init__(self):
        # Maps user_id -> List[WebSocket]
        self.active_connections: Dict[int, List[WebSocket]] = {}
        # Maps socket -> (tenant_id, user_id)
        self.socket_info: Dict[WebSocket, Tuple[int, int]] = {}

    async def connect(self, websocket: WebSocket, user_id: int, tenant_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        self.socket_info[websocket] = (tenant_id, user_id)
        logger.info(f"WebSocket connected for user {user_id} (tenant {tenant_id})")

    def disconnect(self, websocket: WebSocket):
        info = self.socket_info.get(websocket)
        if info:
            tenant_id, user_id = info
            if user_id in self.active_connections:
                if websocket in self.active_connections[user_id]:
                    self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
            del self.socket_info[websocket]
            logger.info(f"WebSocket disconnected for user {user_id}")

    async def broadcast_to_department(self, tenant_id: int, whatsapp_number_id: int, message_data: dict):
        """
        Sends payload to all active websockets belonging to the same tenant.
        (In production, can be filtered strictly by user_number_access cache).
        """
        for ws, (t_id, u_id) in list(self.socket_info.items()):
            if t_id == tenant_id:
                try:
                    await ws.send_json(message_data)
                except Exception as e:
                    logger.error(f"Failed to send websocket message to user {u_id}: {e}")

    async def broadcast(self, message_data: dict):
        """
        Sends payload to all active websockets across all connected users.
        """
        for ws, (t_id, u_id) in list(self.socket_info.items()):
            try:
                await ws.send_json(message_data)
            except Exception as e:
                logger.error(f"Failed to broadcast websocket message to user {u_id}: {e}")

manager = ConnectionManager()

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...)
):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = int(payload.get("sub"))
        tenant_id = int(payload.get("tenant_id"))
    except Exception:
        await websocket.close(code=4001)
        return

    await manager.connect(websocket, user_id=user_id, tenant_id=tenant_id)
    try:
        while True:
            data = await websocket.receive_text()
            # Can process ping / heartbeat or client messages if needed
    except WebSocketDisconnect:
        manager.disconnect(websocket)
