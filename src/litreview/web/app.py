from __future__ import annotations

from importlib import resources

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ..archive import Archive


def create_app(archive: Archive) -> FastAPI:
    app = FastAPI()
    tpl_dir = resources.files("litreview.web").joinpath("templates")
    templates = Jinja2Templates(directory=str(tpl_dir))

    @app.get("/", response_class=HTMLResponse)
    def digest(request: Request):
        return templates.TemplateResponse(
            request, "digest.html", {"summaries": archive.unread_summaries()}
        )

    @app.get("/archive", response_class=HTMLResponse)
    def archive_view(request: Request, q: str | None = None):
        return templates.TemplateResponse(
            request, "archive.html",
            {"summaries": archive.archived_summaries(query=q), "q": q or ""},
        )

    @app.get("/status", response_class=HTMLResponse)
    def status(request: Request):
        return templates.TemplateResponse(
            request, "status.html", {"run": archive.last_run()}
        )

    @app.post("/read/{summary_id}")
    def read(summary_id: int):
        archive.mark_read(summary_id)
        return Response(status_code=200)

    @app.post("/read-all")
    def read_all():
        archive.mark_all_read()
        return RedirectResponse(url="/", status_code=303)

    @app.post("/rate/{summary_id}")
    def rate(summary_id: int, rating: int = Form(...)):
        archive.set_rating(summary_id, rating)  # reserved; unused in v1
        return Response(status_code=200)

    return app
