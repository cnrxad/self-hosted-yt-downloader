from typing import List
from pydantic import BaseModel, Field

class VideoRequest(BaseModel):
    """Datos enviados desde el formulario del Frontend."""
    url: str = Field(..., title="URL del vídeo", description="Enlace de YouTube")
    title: str | None = Field(None, title="Título opcional")

class VideoResponse(BaseModel):
    """Respuesta enviada al cliente."""
    id: int
    url: str
    title: str
    duration: float
    thumbnail_url: str