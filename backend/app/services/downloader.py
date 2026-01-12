import yt_dlp
from pathlib import Path
from typing import Dict, Any

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

def download_video(video_url: str) -> Dict[str, Any]:
    ytdl_opts: Dict[str, Any] = {
        "format": "best",
        "outtmpl": str(DOWNLOADS_DIR / "%(title)s-%(id)s.%(ext)s"),
        "quiet": True,
    }

    with yt_dlp.YoutubeDL(ytdl_opts) as ydl: #type: ignore
        result = ydl.extract_info(video_url, download=True)

    return {
        "id": result["id"],
        "title": result.get("title"),
        "duration": result.get("duration"),
        "thumbnail_url": result.get("thumbnail"),
        "filename": ydl.prepare_filename(result),
    }
