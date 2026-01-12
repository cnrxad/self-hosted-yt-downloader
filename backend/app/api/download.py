from fastapi.responses import StreamingResponse
import subprocess
from fastapi import APIRouter
from yt_dlp import YoutubeDL
from app.models.schemas import VideoRequest

router = APIRouter()

@router.get("/download")
def download(url: str, format: str):

    if format == "mp3":
        cmd = [
            "yt-dlp",
            "-f", "bestaudio",
            "-o", "-",
            url
        ]
        headers = {
            "Content-Disposition": "attachment; filename=audio.mp3"
        }
    else:
        fmt = {
            "best": "best[ext=mp4]",
            "1080p": "best[height<=1080][ext=mp4]",
            "360p": "best[height<=360][ext=mp4]",
        }[format]

        cmd = [
            "yt-dlp",
            "-f", fmt,
            "-o", "-",
            url
        ]
        headers = {
            "Content-Disposition": "attachment; filename=video.mp4"
        }

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE
    )

    if process.stdout is None:
        raise ValueError("Failed to start subprocess")

    return StreamingResponse(
        process.stdout,
        media_type="application/octet-stream",
        headers=headers
    )
