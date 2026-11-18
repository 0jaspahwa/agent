"""The React interface (frontend/dist, built by `npm run build` or the Dockerfile's first stage).

Files under /assets are served as they are; every other path that is not the API, the operations pages or
the API docs returns index.html, so the browser's router can show the right screen after a reload. If the
interface has not been built (tests, a fresh checkout), / says so and points to /ops. Included last, so it
never hides a real route.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
NOT_OURS = ("api/", "ops", "docs", "redoc", "openapi.json", "assets/")
router = APIRouter()

NOT_BUILT = """<!doctype html><html><head><meta charset='utf-8'><title>Corvo procurement</title></head>
<body style='font-family:system-ui;max-width:640px;margin:2rem auto'><h1>Corvo procurement</h1>
<p>The interface has not been built on this server. The operations pages work without it: <a href='/ops'>/ops</a>.</p>
<p>To build it: <code>cd frontend && npm install && npm run build</code>.</p></body></html>"""


def mount(app):
    if (DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")
    app.include_router(router)


@router.get("/{path:path}", include_in_schema=False)
def interface(path: str):
    if path.startswith(NOT_OURS):
        raise HTTPException(404, "Not found.")
    index = DIST / "index.html"
    if not index.is_file():
        return HTMLResponse(NOT_BUILT)
    file = (DIST / path).resolve()
    if path and file.is_file() and DIST in file.parents:  # e.g. a favicon at the top of dist
        return FileResponse(file)
    return FileResponse(index)
