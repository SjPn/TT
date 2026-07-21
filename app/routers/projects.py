from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session
from urllib.parse import quote

from app.database import get_db
from app.deps import (
    get_accessible_projects,
    require_project_access,
    require_project_owner,
    require_user,
)
from app.models import User
from app.services import (
    MemberError,
    add_project_member,
    build_project_export_zip,
    create_project,
    delete_project,
    update_project,
)
from app.templating import templates

router = APIRouter(tags=["projects"])


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    q: str | None = Query(None),
    flash: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    projects = get_accessible_projects(db, user)
    needle = (q or "").strip().lower()
    if needle:
        projects = [
            p
            for p in projects
            if needle in p.name.lower()
            or needle in p.key.lower()
            or needle in (p.description or "").lower()
        ]
    return templates.TemplateResponse(
        request,
        "projects/index.html",
        {"user": user, "projects": projects, "q": q or "", "flash": flash},
    )


@router.post("/projects", response_class=HTMLResponse)
def create_project_route(
    request: Request,
    name: str = Form(...),
    key: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if not name.strip():
        projects = get_accessible_projects(db, user)
        return templates.TemplateResponse(
            request,
            "projects/index.html",
            {
                "user": user,
                "projects": projects,
                "q": "",
                "error": "Укажите название проекта",
            },
            status_code=400,
        )
    project = create_project(
        db,
        owner=user,
        name=name,
        description=description,
        key=key.strip() or None,
    )
    return RedirectResponse(f"/projects/{project.id}?flash=project", status_code=303)


@router.post("/projects/{project_id}/edit")
def edit_project_route(
    project_id: int,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_owner(db, user, project_id)
    if not name.strip():
        return RedirectResponse(f"/projects/{project.id}", status_code=303)
    update_project(db, project=project, name=name, description=description)
    return RedirectResponse(f"/projects/{project.id}?flash=project_saved", status_code=303)


@router.post("/projects/{project_id}/delete")
def delete_project_route(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_owner(db, user, project_id)
    delete_project(db, project=project)
    return RedirectResponse("/?flash=project_deleted", status_code=303)


@router.get("/projects/{project_id}/export")
def export_project_route(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    payload = build_project_export_zip(db, project)
    filename = f"{project.key}-export.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/projects/{project_id}/members")
def add_member_route(
    project_id: int,
    email: str = Form(...),
    return_view: str = Form("list"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    try:
        added = add_project_member(db, project=project, email=email)
        msg = quote(f"Добавлен {added.name} ({added.email})")
        return RedirectResponse(
            f"/projects/{project.id}?view={return_view}&member_ok={msg}",
            status_code=303,
        )
    except MemberError as exc:
        msg = quote(exc.message)
        return RedirectResponse(
            f"/projects/{project.id}?view={return_view}&member_error={msg}",
            status_code=303,
        )
