from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_user
from app.models import User
from app.services import list_notifications, mark_notifications_read
from app.templating import templates

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    items = list_notifications(db, user, limit=50)
    return templates.TemplateResponse(
        request,
        "notifications/index.html",
        {"user": user, "notifications": items},
    )


@router.get("/notifications/{notification_id}/open")
def open_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    from app.models import Notification

    item = db.get(Notification, notification_id)
    if item and item.user_id == user.id:
        mark_notifications_read(db, user, notification_id=notification_id)
        if item.link:
            return RedirectResponse(item.link, status_code=303)
    return RedirectResponse("/notifications", status_code=303)


@router.post("/notifications/read-all")
def read_all(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    mark_notifications_read(db, user)
    return RedirectResponse("/notifications", status_code=303)
