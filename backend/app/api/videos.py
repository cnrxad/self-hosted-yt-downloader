from fastapi import APIRouter, HTTPException
from app.models.schemas import VideoRequest, VideoResponse
from app.services.downloader import download_video

router = APIRouter()

@router.post("/videos", response_model=VideoResponse)
async def post_video(req: VideoRequest):
    try:
        meta = download_video(req.url)
        return VideoResponse(
            id=int(meta["id"]),
            url=meta["filename"],
            title=req.title or meta["title"],
            duration=meta["duration"],
            thumbnail_url=meta["thumbnail_url"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
