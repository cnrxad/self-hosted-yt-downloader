#cnrxad - 2026

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from io import BytesIO
from typing import Any
from copy import deepcopy
from yt_dlp import YoutubeDL
from .api.analyze import router as analyze_router
import tempfile
import os
import re
import glob
import traceback
from urllib.parse import urlparse, parse_qs, urlunparse
import re
from fastapi import WebSocket, WebSocketDisconnect
import json


app = FastAPI(
    title="YT Downloader API",
    description="API para descargar videos de YouTube y obtener calidades",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(analyze_router, prefix="/api")


progress_connections: set[WebSocket] = set()

@app.websocket("/ws/progress")
async def progress_ws(ws: WebSocket):
    await ws.accept()
    progress_connections.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        progress_connections.discard(ws)
        
async def broadcast_progress(percent: float):
    dead = set()
    for ws in progress_connections:
        try:
            await ws.send_text(json.dumps({
                "type": "progress",
                "value": percent
            }))
        except Exception:
            dead.add(ws)
    progress_connections.difference_update(dead)


def extraer_video_id(url: str) -> str | None:
    """Extrae SOLO el video ID de cualquier URL de YouTube"""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'\/shorts\/([0-9A-Za-z_-]{11})',
        r'embed\/([0-9A-Za-z_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def es_playlist_pura(url: str) -> bool:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    # Playlist sin vídeo explícito
    return "list" in qs and "v" not in qs and not extraer_video_id(url)

BLOCKED_PARAMS = {
    "list",
    "index",
    "start_radio",
    "radio",
    "pp",
    "feature"
}

def sanitize_youtube_url(url: str) -> str | None:
    video_id = extraer_video_id(url)
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"

@app.get("/")
def root():
    return {"message": "YT Downloader API funcionando"}


def progress_hook(d):
    if d["status"] == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes")
        if total and downloaded:
            percent = round(downloaded / total * 100, 2)
            import asyncio
            asyncio.create_task(broadcast_progress(percent))

    elif d["status"] == "finished":
        import asyncio
        asyncio.create_task(broadcast_progress(100))



@app.get("/api/download")
async def download_video(url: str = Query(...), format: str = Query(...)):
    try:
        # 1. RECHAZAMOS playlists puras
        if es_playlist_pura(url):
            return {"error": "No se permiten enlaces de playlist completos, solo vídeos individuales."}

        # 2. SANITIZAMOS URL
        clean_url = sanitize_youtube_url(url)
        if not clean_url:
            return {"error": "URL de YouTube no válida o no se pudo extraer el vídeo"}

        # 3. RECHAZAMOS playlists puras
        if es_playlist_pura(url):
            return {"error": "No se permiten enlaces de playlist completos, solo vídeos individuales."}

        buffer = BytesIO()
        
        # OPCIONES MÁXIMAS - URL YA ES SOLO VÍDEO
        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "noplaylist": True,
            "playlistend": 1,
            "progress_hooks": [progress_hook],
            "extractor_args": {
                "youtube": {
                    "skip": ["playlists", "channels"]
                }
            },
        }
        
        postprocessors = None
        ext = "mp4"
        filename = None
        requested_height = None
        real_resolution = None

        # MP3 o MP4
        if format.lower() == "mp3":
            ext = "mp3"
            postprocessors = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
            ydl_format = "bestaudio/best"
        else:
            ext = "mp4"
            ydl_format = "bestvideo+bestaudio/best"
            match = re.match(r"(\d+)p", format.lower())
            if match:
                requested_height = int(match.group(1))

        # Extraemos info del VÍDEO ESPECÍFICO
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)  # <- URL LIMPIA
            
            if info.get("_type") == "playlist":
                return {"error": "Error interno: detección de playlist imposible"}

            title = info.get("title") or ("audio" if ext == "mp3" else "video")
            safe_title = re.sub(r'[^a-zA-Z0-9_\- ]', '', title)
            filename = f"{safe_title}.{ext}"

            # Selección formato MP4
            if ext == "mp4":
                formats_list = info.get("formats") or []
                candidates = [
                    f for f in formats_list
                    if f.get("vcodec") not in (None, "none") and f.get("height") is not None
                ]

                if candidates:
                    if requested_height:
                        candidates = [f for f in candidates if f["height"] <= requested_height]
                    if candidates:
                        best_candidate = max(candidates, key=lambda x: x.get("height", 0))
                        real_resolution = best_candidate.get("height", None)
                        if best_candidate.get("acodec") != "none" and best_candidate.get("vcodec") != "none":
                            ydl_format = best_candidate.get("format_id") or ydl_format
                        else:
                            ydl_format = "bestvideo+bestaudio/best"
                    else:
                        ydl_format = "bestvideo+bestaudio/best"
                else:
                    ydl_format = "bestvideo+bestaudio/best"

        # Descarga
        with tempfile.TemporaryDirectory() as tmpdir:
            outtmpl = os.path.join(tmpdir, "%(title)s.%(ext)s")
            ydl_opts_file = deepcopy(ydl_opts)
            ydl_opts_file.update({
                "outtmpl": outtmpl,
                "format": ydl_format,
            })
            if postprocessors is not None:
                ydl_opts_file["postprocessors"] = postprocessors

            with YoutubeDL(ydl_opts_file) as ydl:
                ydl.download([clean_url])  # <- URL LIMPIA

            file_list = glob.glob(os.path.join(tmpdir, f"*.{ext}"))
            if not file_list:
                return {"error": "No se generó el archivo descargado"}

            with open(file_list[0], "rb") as f:
                buffer.write(f.read())

        buffer.seek(0)
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        response = StreamingResponse(buffer, media_type="application/octet-stream", headers=headers)
        if ext == "mp4":
            response.headers["X-Video-Resolution"] = str(real_resolution or "unknown")

        return response

    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}
