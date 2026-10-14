from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

router = APIRouter()

INDEX_FILE = Path(__file__).resolve().parent.parent / "static" / "index.html"


@router.get("/ui", include_in_schema=False)
def ui_page():
    return FileResponse(INDEX_FILE, media_type="text/html")


@router.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui")