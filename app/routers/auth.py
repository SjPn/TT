from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import (
    create_session_token,
    create_user,
    get_user_by_email,
    update_user_profile,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.deps import get_current_user, require_user
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
            {"error": "Неверный email или пароль", "email": email},
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
                "error": "Пароль не короче 6 символов",
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
                "error": "Этот email уже зарегистрирован",
                "email": email,
                "name": name,
            },
            status_code=400,
        )
    user = create_user(db, email=email, name=name, password=password)
    redirect = RedirectResponse("/", status_code=303)
    _set_session_cookie(redirect, request, user.id)
    return redirect


@router.get("/profile", response_class=HTMLResponse)
def profile_page(
    request: Request,
    flash: str | None = Query(None),
    user: User = Depends(require_user),
):
    return templates.TemplateResponse(
        request,
        "auth/profile.html",
        {
            "user": user,
            "error": None,
            "name": user.name,
            "email": user.email,
            "flash": flash,
        },
    )


@router.post("/profile", response_class=HTMLResponse)
def profile_save(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(""),
    password_confirm: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    name = name.strip()
    email = email.strip()
    password = password.strip()
    password_confirm = password_confirm.strip()

    def fail(msg: str):
        return templates.TemplateResponse(
            request,
            "auth/profile.html",
            {
                "user": user,
                "error": msg,
                "name": name,
                "email": email,
                "flash": None,
            },
            status_code=400,
        )

    if not name:
        return fail("Укажите имя")
    if not email or "@" not in email:
        return fail("Укажите корректный email для входа")

    other = get_user_by_email(db, email)
    if other and other.id != user.id:
        return fail("Этот email уже занят")

    if password or password_confirm:
        if len(password) < 6:
            return fail("Новый пароль не короче 6 символов")
        if password != password_confirm:
            return fail("Пароли не совпадают")

    update_user_profile(
        db,
        user=user,
        name=name,
        email=email,
        password=password or None,
    )
    return RedirectResponse("/profile?flash=profile", status_code=303)


@router.post("/logout")
def logout(request: Request):
    redirect = RedirectResponse("/login", status_code=303)
    redirect.delete_cookie(
        settings.session_cookie,
        secure=request.url.scheme == "https",
    )
    return redirect
