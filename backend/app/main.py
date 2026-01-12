# cnrxad - 2026

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse
from yt_dlp import YoutubeDL
from copy import deepcopy
from app.api.analyze import router as analyze_router

import tempfile
import os
import re
import glob
import traceback
import json
import sys
from io import BytesIO
from urllib.parse import urlparse, parse_qs
from threading import Thread
import webbrowser
import uvicorn

# -------------------------------
# APP
# -------------------------------
app = FastAPI(
    title="cnrxad's self hosted yt downloader - API",
    description="cnrxad - API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router, prefix="/api")

# -------------------------------
# Uvicorn server (GLOBAL)
# -------------------------------
server: uvicorn.Server | None = None

# -------------------------------
# WebSocket progress
# -------------------------------
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

# -------------------------------
# YouTube helpers
# -------------------------------
def extraer_video_id(url: str) -> str | None:
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
    return "list" in qs and "v" not in qs and not extraer_video_id(url)

def sanitize_youtube_url(url: str) -> str | None:
    video_id = extraer_video_id(url)
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"

# -------------------------------
# yt-dlp progress hook
# -------------------------------
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

# -------------------------------
# API
# -------------------------------
@app.get("/api")
def root_api():
    return {"message": "YT Downloader API funcionando"}

@app.get("/api/download")
async def download_video(
    url: str = Query(...),
    format: str = Query(...)
):
    try:
        if es_playlist_pura(url):
            return {"error": "No se permiten playlists completas"}

        clean_url = sanitize_youtube_url(url)
        if not clean_url:
            return {"error": "URL de YouTube no válida"}

        buffer = BytesIO()

        ydl_opts = {
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

        ext = "mp4"
        postprocessors = None
        requested_height = None

        if format.lower() == "mp3":
            ext = "mp3"
            ydl_format = "bestaudio/best"
            postprocessors = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            match = re.match(r"(\d+)p", format.lower())
            MAX_HEIGHT = 1080
            requested_height = min(
                int(match.group(1)) if match else MAX_HEIGHT,
                MAX_HEIGHT
            )
            ydl_format = "bestvideo+bestaudio/best"

        # Obtener info
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            title = info.get("title", "video")
            safe_title = re.sub(r'[^a-zA-Z0-9_\- ]', '', title)
            filename = f"{safe_title}.{ext}"

            best_candidate = None
            if ext == "mp4":
                formats_list = info.get("formats", [])
                candidates = [
                    f for f in formats_list
                    if f.get("vcodec") != "none"
                    and f.get("acodec") != "none"
                    and f.get("height", 0) <= requested_height
                ]
                if candidates:
                    best_candidate = max(
                        candidates,
                        key=lambda x: x.get("height", 0)
                    )
                    ydl_format = best_candidate.get("format_id", ydl_format)

        # Descargar
        with tempfile.TemporaryDirectory() as tmpdir:
            outtmpl = os.path.join(tmpdir, "%(title)s.%(ext)s")

            ydl_opts_file = deepcopy(ydl_opts)
            ydl_opts_file.update({
                "outtmpl": outtmpl,
                "format": ydl_format,
            })

            if postprocessors:
                ydl_opts_file["postprocessors"] = postprocessors

            with YoutubeDL(ydl_opts_file) as ydl:
                ydl.download([clean_url])

            files = glob.glob(os.path.join(tmpdir, f"*.{ext}"))
            if not files:
                return {"error": "No se generó el archivo"}

            with open(files[0], "rb") as f:
                buffer.write(f.read())

        buffer.seek(0)

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"'
        }

        response = StreamingResponse(
            buffer,
            media_type="application/octet-stream",
            headers=headers,
        )

        if ext == "mp4" and best_candidate:
            response.headers["X-Video-Resolution"] = str(
                best_candidate.get("height", "unknown")
            )

        return response

    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}

# -------------------------------
# SHUTDOWN (FUNCIONA)
# -------------------------------
@app.post("/api/shutdown")
async def shutdown():
    global server
    if server:
        server.should_exit = True
        return {"message": "Servidor cerrándose..."}
    return {"error": "Servidor no inicializado"}

# -------------------------------
# FRONTEND
# -------------------------------
def get_base_path():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

frontend_dist = os.path.abspath(
    os.path.join(get_base_path(), "frontend", "dist")
)

app.mount(
    "/",
    StaticFiles(directory=frontend_dist, html=True),
    name="frontend",
)

# -------------------------------
# SERVER
# -------------------------------
def start_server():
    global server
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=4321,
        log_config=None,
    )
    server = uvicorn.Server(config)
    server.run()

if __name__ == "__main__":
    Thread(
        target=lambda: webbrowser.open("http://localhost:4321"),
        daemon=True
    ).start()

    start_server()
