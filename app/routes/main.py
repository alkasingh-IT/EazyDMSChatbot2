"""DMS Main Route — serves the SPA index page."""
from fastapi import APIRouter
from fastapi.responses import FileResponse
from ..config.settings import settings

router = APIRouter()


@router.get("/", include_in_schema=False)
async def serve_index():
    index = settings.STATIC_DIR / "index.html"
    return FileResponse(str(index))


@router.get("/health")
async def health():
    return {"status": "ok", "app": "DMS Analytics"}
