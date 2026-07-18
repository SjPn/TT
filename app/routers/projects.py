from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
    create_project,
    delete_project,
    update_project,
)
from app.templating import templates

router = APIRouter(tags=["projects"])


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    projects = get_accessible_projects(db, user)
    return templates.TemplateResponse(
        request,
        "projects/index.html",
        {"user": user, "projects": projects},
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
            {"user": user, "projects": projects, "error": "Project name is required"},
            status_code=400,
        )
    project = create_project(
        db,
        owner=user,
        name=name,
        description=description,
        key=key.strip() or None,
    )
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


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
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.post("/projects/{project_id}/delete")
def delete_project_route(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_owner(db, user, project_id)
    delete_project(db, project=project)
    return RedirectResponse("/", status_code=303)


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
        msg = quote(f"Added {added.name} ({added.email})")
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
