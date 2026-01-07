from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.models import Event
from app.api.routes.schemas_extended import EventResponse

router = APIRouter()

@router.get("/", response_model=List[EventResponse])
async def get_alarms(
    skip: int = 0, 
    limit: int = 50, 
    camera_id: Optional[int] = None,
    event_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(Event).order_by(desc(Event.created_at)).offset(skip).limit(limit)
    
    if camera_id:
        query = query.where(Event.camera_id == camera_id)
    if event_type:
        query = query.where(Event.event_type == event_type)
        
    result = await db.execute(query)
    alarms = result.scalars().all()
    return alarms

@router.get("/{alarm_id}", response_model=EventResponse)
async def get_alarm(alarm_id: UUID, db: AsyncSession = Depends(get_db)):
    alarm = await db.get(Event, alarm_id)
    if not alarm:
        raise HTTPException(status_code=404, detail="Alarm not found")
    return alarm
