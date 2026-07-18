from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import create_session_token, create_user, get_user_by_email, verify_password
from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.templating import templates

router = APIRouter(tags=["auth"])


def _set_session_cookie(response: RedirectResponse, request: Request, user_id: int) -> None:
    # Secure cookies only work on HTTPS; HTTP sslip.io must not set Secure.
    secure = request.url.scheme == "https"
    response.set_cookie(
        settings.session_cookie,
        create_session_token(user_id),
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=settings.session_max_age,
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: User | None = Depends(get_current_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"error": None, "email": ""},
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_user_by_email(db, email)
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Invalid email or password", "email": email},
            status_code=400,
        )
    redirect = RedirectResponse("/", status_code=303)
    _set_session_cookie(redirect, request, user.id)
    return redirect


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, user: User | None = Depends(get_current_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "auth/register.html",
        {"error": None, "email": "", "name": ""},
    )


@router.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if len(password) < 6:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {
                "error": "Password must be at least 6 characters",
                "email": email,
                "name": name,
            },
            status_code=400,
        )
    if get_user_by_email(db, email):
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {
                "error": "Email already registered",
                "email": email,
                "name": name,
            },
            status_code=400,
        )
    user = create_user(db, email=email, name=name, password=password)
    redirect = RedirectResponse("/", status_code=303)
    _set_session_cookie(redirect, request, user.id)
    return redirect


@router.post("/logout")
def logout(request: Request):
    redirect = RedirectResponse("/login", status_code=303)
    redirect.delete_cookie(
        settings.session_cookie,
        secure=request.url.scheme == "https",
    )
    return redirect
