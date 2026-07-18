from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.deps import get_current_user
from app.routers import auth, issues, notifications, projects
from app.services import (
    list_notifications,
    migrate_attachment_comment_id,
    migrate_legacy_statuses,
    unread_notification_count,
)

DATA_DIR = Path(settings.data_dir)
STATIC_DIR = Path(__file__).resolve().parent / "static"
UPLOAD_DIR = DATA_DIR / "uploads"


class AuthRedirectMiddleware(BaseHTTPMiddleware):
    PUBLIC_PREFIXES = ("/login", "/register", "/static", "/health")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(self.PUBLIC_PREFIXES) or path == "/favicon.ico":
            return await call_next(request)

        db = SessionLocal()
        try:
            user = get_current_user(request, db)
            if user is None:
                return RedirectResponse("/login", status_code=303)
            request.state.unread_count = unread_notification_count(db, user)
            request.state.notifications = list_notifications(db, user, limit=8)
        finally:
            db.close()

        return await call_next(request)


def create_app() -> FastAPI:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    migrate_attachment_comment_id(engine)

    db = SessionLocal()
    try:
        migrate_legacy_statuses(db)
    finally:
        db.close()

    app = FastAPI(title=settings.app_name)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    app.add_middleware(AuthRedirectMiddleware)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(issues.router)
    app.include_router(notifications.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
