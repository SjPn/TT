from __future__ import annotations

import re

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import parse_session_token
from app.config import settings
from app.database import get_db
from app.models import Project, ProjectMember, User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(settings.session_cookie)
    if not token:
        return None
    user_id = parse_session_token(token)
    if not user_id:
        return None
    return db.get(User, user_id)


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def slugify_key(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", name.upper())
    return (cleaned[:8] or "PROJ")


def user_can_access_project(db: Session, user: User, project: Project) -> bool:
    if project.owner_id == user.id:
        return True
    membership = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
        .first()
    )
    return membership is not None


def get_accessible_projects(db: Session, user: User) -> list[Project]:
    owned = db.query(Project).filter(Project.owner_id == user.id).all()
    member_ids = [
        m.project_id
        for m in db.query(ProjectMember).filter(ProjectMember.user_id == user.id).all()
    ]
    shared = (
        db.query(Project).filter(Project.id.in_(member_ids)).all() if member_ids else []
    )
    by_id = {p.id: p for p in owned + shared}
    return sorted(by_id.values(), key=lambda p: p.name.lower())


def get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def require_project_access(
    db: Session, user: User, project_id: int
) -> Project:
    project = get_project_or_404(db, project_id)
    if not user_can_access_project(db, user, project):
        raise HTTPException(status_code=403, detail="No access to this project")
    return project


def project_members(db: Session, project: Project) -> list[User]:
    users = {project.owner.id: project.owner}
    for member in project.members:
        users[member.user.id] = member.user
    return sorted(users.values(), key=lambda u: u.name.lower())
