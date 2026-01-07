from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from typing import List
from app.api.routes.schemas_extended import FaceResponse
import base64
import json
import logging
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.core.database import get_db
from fastapi import Depends

# We need a Face model or reuse "faces" table via raw SQL or define a model?
# For now, we will query the 'faces' table using text SQL or define the Model in models.py
# Let's check models.py first. It doesn't have Face model. We should add it or use raw SQL.
# Using Raw SQL for faces table since it has 'vector' type which might need special handling.
from sqlalchemy import text

router = APIRouter()
logger = logging.getLogger("router.faces")

@router.post("/")
async def register_face(
    request: Request,
    file: UploadFile = File(...), 
    name: str = Form(...)
):
    """
    Uploads an image to register a face.
    Publishes to NATS 'commands.register_face'.
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type")

    content = await file.read()
    
    # Encode to Base64 to send over JSON NATS
    img_b64 = base64.b64encode(content).decode('utf-8')
    
    nc = request.app.state.nc
    if not nc:
         raise HTTPException(status_code=503, detail="NATS unavailable")
         
    payload = {
        "name": name,
        "image": img_b64
    }
    
    try:
        # Request-Reply pattern? Or just Publish? 
        # Request-Reply is better to know if it succeeded.
        response = await nc.request("commands.register_face", json.dumps(payload).encode(), timeout=5.0)
        res_data = json.loads(response.data.decode())
        
        if res_data.get("status") == "error":
            raise HTTPException(status_code=400, detail=res_data.get("message"))
            
        return res_data
        
    except asyncio.TimeoutError:
         raise HTTPException(status_code=504, detail="Inference service timed out")
    except Exception as e:
         logger.error(f"Face registration error: {e}")
         raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=List[FaceResponse])
async def list_faces(db: AsyncSession = Depends(get_db)):
    from app.models import Face
    from app.api.routes.schemas_extended import FaceResponse
    try:
        # Sort by creation time desc
        result = await db.execute(select(Face).order_by(Face.created_at.desc()))
        faces = result.scalars().all()
        return faces
    except Exception as e:
        logger.error(f"List faces error: {e}")
        raise HTTPException(status_code=500, detail="Database error")

@router.delete("/{face_id}")
async def delete_face(face_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    from app.models import Face
    try:
        face = await db.get(Face, face_id)
        if not face:
            raise HTTPException(status_code=404, detail="Face not found")
            
        await db.delete(face)
        await db.commit()
        
        # Notify Inference to reload?
        nc = request.app.state.nc
        if nc:
            await nc.publish("commands.reload_faces", b"")
            
        return {"status": "deleted", "id": face_id}
    except Exception as e:
        await db.rollback()
        logger.error(f"Delete face error: {e}")
        raise HTTPException(status_code=500, detail="Database error")
