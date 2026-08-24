import logging
from typing import List, Optional
from datetime import datetime, date, time
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import CalendarEvent, User, Contact, Conversation, Message
from app.schemas.schemas import (
    CalendarEventCreate,
    CalendarEventUpdate,
    CalendarEventResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["Calendar & Tasks"])

def _format_event_response(event: CalendarEvent) -> CalendarEventResponse:
    contact_name = event.contact.nome if event.contact else None
    contact_phone = event.contact.telefone if event.contact else None
    return CalendarEventResponse(
        id=event.id,
        tenant_id=event.tenant_id,
        user_id=event.user_id,
        contact_id=event.contact_id,
        conversation_id=event.conversation_id,
        message_id=event.message_id,
        title=event.title,
        description=event.description,
        start_time=event.start_time,
        end_time=event.end_time,
        all_day=event.all_day,
        color=event.color,
        priority=event.priority,
        status=event.status,
        reminder_minutes=event.reminder_minutes,
        criado_em=event.criado_em,
        atualizado_em=event.atualizado_em,
        contact_name=contact_name,
        contact_phone=contact_phone
    )

@router.get("/events", response_model=List[CalendarEventResponse])
async def list_calendar_events(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    priority_filter: Optional[str] = Query(None, alias="priority"),
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Lists calendar events for the authenticated user (isolated per user).
    Supports filtering by date range, priority, status and search text.
    """
    stmt = (
        select(CalendarEvent)
        .options(selectinload(CalendarEvent.contact), selectinload(CalendarEvent.conversation))
        .where(
            CalendarEvent.tenant_id == current_user.tenant_id,
            CalendarEvent.user_id == current_user.id
        )
    )

    if start_date:
        stmt = stmt.where(CalendarEvent.start_time >= start_date)
    if end_date:
        stmt = stmt.where(CalendarEvent.start_time <= end_date)
    if status_filter:
        stmt = stmt.where(CalendarEvent.status == status_filter)
    if priority_filter:
        stmt = stmt.where(CalendarEvent.priority == priority_filter)
    if search:
        search_fmt = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                CalendarEvent.title.ilike(search_fmt),
                CalendarEvent.description.ilike(search_fmt)
            )
        )

    stmt = stmt.order_by(CalendarEvent.start_time.asc())
    res = await db.execute(stmt)
    events = res.scalars().all()
    return [_format_event_response(e) for e in events]

@router.get("/summary")
async def get_calendar_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns high-level stats for user task badges (today pending count, overdue count, etc.)
    """
    today_start = datetime.combine(date.today(), time.min)
    today_end = datetime.combine(date.today(), time.max)

    # Today pending count
    today_stmt = select(func.count(CalendarEvent.id)).where(
        CalendarEvent.tenant_id == current_user.tenant_id,
        CalendarEvent.user_id == current_user.id,
        CalendarEvent.status != "concluido",
        CalendarEvent.status != "cancelado",
        CalendarEvent.start_time >= today_start,
        CalendarEvent.start_time <= today_end
    )
    today_res = await db.execute(today_stmt)
    today_pending = today_res.scalar() or 0

    # Overdue pending count
    overdue_stmt = select(func.count(CalendarEvent.id)).where(
        CalendarEvent.tenant_id == current_user.tenant_id,
        CalendarEvent.user_id == current_user.id,
        CalendarEvent.status != "concluido",
        CalendarEvent.status != "cancelado",
        CalendarEvent.start_time < today_start
    )
    overdue_res = await db.execute(overdue_stmt)
    overdue = overdue_res.scalar() or 0

    # Total pending
    total_stmt = select(func.count(CalendarEvent.id)).where(
        CalendarEvent.tenant_id == current_user.tenant_id,
        CalendarEvent.user_id == current_user.id,
        CalendarEvent.status != "concluido",
        CalendarEvent.status != "cancelado"
    )
    total_res = await db.execute(total_stmt)
    total_pending = total_res.scalar() or 0

    return {
        "today_pending": today_pending,
        "overdue": overdue,
        "total_pending": total_pending
    }

@router.post("/events", response_model=CalendarEventResponse, status_code=status.HTTP_201_CREATED)
async def create_calendar_event(
    payload: CalendarEventCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Creates a new calendar task or appointment for the authenticated user.
    """
    new_event = CalendarEvent(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        contact_id=payload.contact_id,
        conversation_id=payload.conversation_id,
        message_id=payload.message_id,
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        start_time=payload.start_time,
        end_time=payload.end_time or payload.start_time,
        all_day=payload.all_day,
        color=payload.color or "#10b981",
        priority=payload.priority or "media",
        status=payload.status or "pendente",
        reminder_minutes=payload.reminder_minutes,
        criado_em=datetime.utcnow(),
        atualizado_em=datetime.utcnow()
    )
    db.add(new_event)
    await db.commit()
    await db.refresh(new_event)

    # Load contact if present
    if new_event.contact_id:
        stmt = (
            select(CalendarEvent)
            .options(selectinload(CalendarEvent.contact))
            .where(CalendarEvent.id == new_event.id)
        )
        res = await db.execute(stmt)
        new_event = res.scalar_one()

    return _format_event_response(new_event)

@router.put("/events/{event_id}", response_model=CalendarEventResponse)
async def update_calendar_event(
    event_id: int,
    payload: CalendarEventUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(CalendarEvent)
        .options(selectinload(CalendarEvent.contact))
        .where(
            CalendarEvent.id == event_id,
            CalendarEvent.tenant_id == current_user.tenant_id,
            CalendarEvent.user_id == current_user.id
        )
    )
    res = await db.execute(stmt)
    event = res.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Evento não encontrado ou sem permissão")

    if payload.title is not None:
        event.title = payload.title.strip()
    if payload.description is not None:
        event.description = payload.description.strip() if payload.description else None
    if payload.start_time is not None:
        event.start_time = payload.start_time
    if payload.end_time is not None:
        event.end_time = payload.end_time
    if payload.all_day is not None:
        event.all_day = payload.all_day
    if payload.color is not None:
        event.color = payload.color
    if payload.priority is not None:
        event.priority = payload.priority
    if payload.status is not None:
        event.status = payload.status
    if payload.reminder_minutes is not None:
        event.reminder_minutes = payload.reminder_minutes
    if payload.contact_id is not None:
        event.contact_id = payload.contact_id
    if payload.conversation_id is not None:
        event.conversation_id = payload.conversation_id

    event.atualizado_em = datetime.utcnow()
    await db.commit()
    await db.refresh(event)

    return _format_event_response(event)

@router.patch("/events/{event_id}/toggle", response_model=CalendarEventResponse)
async def toggle_calendar_event_status(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Quick toggle between 'concluido' and 'pendente'.
    """
    stmt = (
        select(CalendarEvent)
        .options(selectinload(CalendarEvent.contact))
        .where(
            CalendarEvent.id == event_id,
            CalendarEvent.tenant_id == current_user.tenant_id,
            CalendarEvent.user_id == current_user.id
        )
    )
    res = await db.execute(stmt)
    event = res.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Evento não encontrado")

    if event.status == "concluido":
        event.status = "pendente"
    else:
        event.status = "concluido"

    event.atualizado_em = datetime.utcnow()
    await db.commit()
    await db.refresh(event)

    return _format_event_response(event)

@router.delete("/events/{event_id}")
async def delete_calendar_event(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(CalendarEvent)
        .where(
            CalendarEvent.id == event_id,
            CalendarEvent.tenant_id == current_user.tenant_id,
            CalendarEvent.user_id == current_user.id
        )
    )
    res = await db.execute(stmt)
    event = res.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Evento não encontrado")

    await db.delete(event)
    await db.commit()
    return {"status": "success", "message": "Evento excluído com sucesso"}
