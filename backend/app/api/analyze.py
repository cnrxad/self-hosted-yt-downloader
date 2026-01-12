from fastapi import APIRouter
from pydantic import BaseModel
from yt_dlp import YoutubeDL
import re

router = APIRouter()


class VideoRequest(BaseModel):
    url: str


# -----------------------------
# HELPERS
# -----------------------------
def extraer_video_id(url: str) -> str | None:
    """
    Extrae el ID de vídeo desde cualquier URL de YouTube
    (watch, shorts, embed, youtu.be, playlists con v=, etc)
    """
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11})",
        r"\/shorts\/([0-9A-Za-z_-]{11})",
        r"embed\/([0-9A-Za-z_-]{11})",
        r"youtu\.be\/([0-9A-Za-z_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def sanitize_youtube_url(url: str) -> str | None:
    """
    Devuelve una URL de YouTube limpia SOLO con ?v=VIDEO_ID
    Elimina playlists, radios, mixes y cualquier parámetro extra.
    """
    video_id = extraer_video_id(url)
    if not video_id:
        return None

    return f"https://www.youtube.com/watch?v={video_id}"


# -----------------------------
# ENDPOINT
# -----------------------------
@router.post("/analyze")
def analyze_video(req: VideoRequest):
    # 1. SANITIZAMOS LA URL (CLAVE)
    clean_url = sanitize_youtube_url(req.url)
    if not clean_url:
        return {"error": "URL de YouTube no válida o no se pudo extraer el vídeo"}

    # 2. OPCIONES yt-dlp ANTI-PLAYLIST DEFINITIVAS
    ydl_opts = {
        "quiet": True,
        "noplaylist": True,
        "playlist_items": "0",
        "extract_flat": True,
    }

    # 3. EXTRAEMOS INFO SOLO DEL VÍDEO
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(clean_url, download=False)

    # 4. BLINDAJE FINAL
    if info.get("_type") == "playlist":
        return {"error": "No se permiten playlists"}

    formats_list = info.get("formats") or []

    # -----------------------------
    # FORMATOS DE VÍDEO
    # -----------------------------
    video_formats = [
        f for f in formats_list
        if f.get("vcodec") not in (None, "none") and f.get("height") is not None
    ]

    heights = sorted({f["height"] for f in video_formats}, reverse=True)

    formats = []

    if heights:
        max_height = heights[0]
        formats.append({"id": "best", "label": f"MP4 · {max_height}p"})

        for h in [1080, 720, 480, 360]:
            if h in heights and h != max_height:
                formats.append({"id": f"{h}p", "label": f"MP4 · {h}p"})

    # -----------------------------
    # FORMATO AUDIO
    # -----------------------------
    audio_formats = [
        f for f in formats_list
        if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none")
    ]

    if audio_formats:
        formats.append({"id": "mp3", "label": "MP3 · Audio"})

    return {
        "title": info.get("title", "Unknown"),
        "formats": formats,
    }
