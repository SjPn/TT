from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.deps import project_members, require_project_access, require_user
from app.models import (
    BOARD_STATUSES,
    PRIORITY_LABELS,
    STATUS_LABELS,
    STATUS_ORDER,
    Comment,
    Issue,
    IssueStatus,
    Priority,
    Project,
    User,
)
from app.services import (
    WorkflowError,
    add_comment,
    confirm_issue_done,
    create_issue,
    issues_by_status,
    list_issues,
    mark_issue_done,
    normalize_labels,
    save_images,
    save_issue_images,
    update_issue_status,
)
from app.templating import templates

router = APIRouter(tags=["issues"])


def _common_ctx(project, user, members):
    return {
        "user": user,
        "project": project,
        "members": members,
        "status_labels": STATUS_LABELS,
        "status_order": STATUS_ORDER,
        "board_statuses": BOARD_STATUSES,
        "priority_labels": PRIORITY_LABELS,
        "priorities": list(Priority),
        "statuses": list(BOARD_STATUSES),
    }


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_issues(
    request: Request,
    project_id: int,
    q: str | None = Query(None),
    status: str | None = Query(None),
    priority: str | None = Query(None),
    view: str = Query("list"),
    member_ok: str | None = Query(None),
    member_error: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    members = project_members(db, project)
    ctx = _common_ctx(project, user, members)
    ctx.update(
        {
            "q": q or "",
            "filter_status": status or "",
            "filter_priority": priority or "",
            "view": view,
            "member_ok": member_ok,
            "member_error": member_error,
        }
    )
    if view == "board":
        ctx["columns"] = issues_by_status(db, project)
        return templates.TemplateResponse(request, "issues/board.html", ctx)

    if view == "archive":
        ctx["issues"] = list_issues(db, project, q=q, priority=priority, archived=True)
        return templates.TemplateResponse(request, "issues/archive.html", ctx)

    ctx["issues"] = list_issues(
        db,
        project,
        q=q,
        status=status,
        priority=priority,
        archived=False,
    )
    return templates.TemplateResponse(request, "issues/list.html", ctx)


@router.post("/projects/{project_id}/issues", response_class=HTMLResponse)
async def create_issue_route(
    request: Request,
    project_id: int,
    title: str = Form(...),
    description: str = Form(""),
    priority: str = Form("p3"),
    labels: str = Form(""),
    assignee_id: str = Form(""),
    photos: Annotated[list[UploadFile], File()] = [],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    assignee = int(assignee_id) if assignee_id.strip().isdigit() else None
    issue = create_issue(
        db,
        project=project,
        author=user,
        title=title,
        description=description,
        priority=priority,
        status=IssueStatus.OPEN,
        labels=labels,
        assignee_id=assignee,
    )
    if photos:
        await save_issue_images(db, issue=issue, files=list(photos))
    return RedirectResponse(f"/projects/{project.id}/issues/{issue.id}", status_code=303)


def _get_issue_or_redirect(db: Session, project: Project, issue_id: int):
    issue = db.get(Issue, issue_id)
    if not issue or issue.project_id != project.id:
        return None
    return issue


@router.get("/projects/{project_id}/issues/{issue_id}/edit", response_class=HTMLResponse)
def issue_edit_page(
    request: Request,
    project_id: int,
    issue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    issue = _get_issue_or_redirect(db, project, issue_id)
    if not issue:
        return RedirectResponse(f"/projects/{project.id}", status_code=303)
    if issue.author_id != user.id:
        return RedirectResponse(
            f"/projects/{project.id}/issues/{issue.id}", status_code=303
        )
    members = project_members(db, project)
    return templates.TemplateResponse(
        request,
        "issues/edit.html",
        {
            **_common_ctx(project, user, members),
            "issue": issue,
        },
    )


@router.get("/projects/{project_id}/issues/{issue_id}", response_class=HTMLResponse)
def issue_detail(
    request: Request,
    project_id: int,
    issue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    issue = (
        db.query(Issue)
        .options(
            joinedload(Issue.assignee),
            joinedload(Issue.author),
            joinedload(Issue.comments).joinedload(Comment.author),
            joinedload(Issue.comments).joinedload(Comment.attachments),
            joinedload(Issue.attachments),
        )
        .filter(Issue.id == issue_id, Issue.project_id == project.id)
        .first()
    )
    if not issue:
        return RedirectResponse(f"/projects/{project.id}", status_code=303)
    members = project_members(db, project)
    return templates.TemplateResponse(
        request,
        "issues/detail.html",
        {
            **_common_ctx(project, user, members),
            "issue": issue,
            "can_mark_done": (
                issue.assignee_id == user.id
                and issue.status
                in (IssueStatus.OPEN, IssueStatus.IN_PROGRESS)
            ),
            "can_confirm": (
                issue.author_id == user.id
                and issue.status == IssueStatus.PENDING_CONFIRM
            ),
        },
    )


@router.post("/projects/{project_id}/issues/{issue_id}", response_class=HTMLResponse)
def update_issue(
    request: Request,
    project_id: int,
    issue_id: int,
    title: str = Form(...),
    description: str = Form(""),
    priority: str = Form("p3"),
    labels: str = Form(""),
    assignee_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    issue = _get_issue_or_redirect(db, project, issue_id)
    if not issue:
        return RedirectResponse(f"/projects/{project.id}", status_code=303)
    if issue.author_id != user.id:
        return RedirectResponse(
            f"/projects/{project.id}/issues/{issue.id}", status_code=303
        )

    issue.title = title.strip()
    issue.description = description.strip()
    issue.priority = priority
    issue.labels = normalize_labels(labels)
    issue.assignee_id = int(assignee_id) if assignee_id.strip().isdigit() else None
    db.add(issue)
    db.commit()
    return RedirectResponse(f"/projects/{project.id}/issues/{issue.id}", status_code=303)


@router.post("/projects/{project_id}/issues/{issue_id}/mark-done")
def mark_done_route(
    project_id: int,
    issue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    issue = _get_issue_or_redirect(db, project, issue_id)
    if not issue:
        return RedirectResponse(f"/projects/{project.id}", status_code=303)
    try:
        mark_issue_done(db, issue=issue, user=user)
    except WorkflowError:
        pass
    return RedirectResponse(f"/projects/{project.id}/issues/{issue.id}", status_code=303)


@router.post("/projects/{project_id}/issues/{issue_id}/confirm")
def confirm_done_route(
    project_id: int,
    issue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    issue = _get_issue_or_redirect(db, project, issue_id)
    if not issue:
        return RedirectResponse(f"/projects/{project.id}", status_code=303)
    try:
        confirm_issue_done(db, issue=issue, user=user)
    except WorkflowError:
        pass
    return RedirectResponse(f"/projects/{project.id}/issues/{issue.id}", status_code=303)


@router.post("/projects/{project_id}/issues/{issue_id}/status", response_class=HTMLResponse)
def change_status(
    request: Request,
    project_id: int,
    issue_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    issue = db.get(Issue, issue_id)
    if not issue or issue.project_id != project.id:
        return HTMLResponse("", status_code=404)
    # Board: only open ↔ in_progress
    allowed = {IssueStatus.OPEN, IssueStatus.IN_PROGRESS}
    if issue.status in allowed and status in allowed:
        update_issue_status(db, issue, status)
    members = project_members(db, project)
    columns = issues_by_status(db, project)
    return templates.TemplateResponse(
        request,
        "partials/board_columns.html",
        {
            **_common_ctx(project, user, members),
            "columns": columns,
        },
    )


@router.post("/projects/{project_id}/issues/{issue_id}/comments", response_class=HTMLResponse)
async def post_comment(
    request: Request,
    project_id: int,
    issue_id: int,
    body: str = Form(""),
    photos: Annotated[list[UploadFile], File()] = [],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    issue = db.get(Issue, issue_id)
    if not issue or issue.project_id != project.id:
        return RedirectResponse(f"/projects/{project.id}", status_code=303)
    if issue.status == IssueStatus.RESOLVED:
        return RedirectResponse(f"/projects/{project.id}/issues/{issue.id}", status_code=303)
    text = body.strip()
    has_photos = any(p.filename for p in photos) if photos else False
    if not text and not has_photos:
        return RedirectResponse(f"/projects/{project.id}/issues/{issue.id}", status_code=303)
    comment = add_comment(db, issue=issue, author=user, body=text or " ")
    if has_photos:
        await save_images(db, issue=issue, files=list(photos), comment=comment)
    return RedirectResponse(f"/projects/{project.id}/issues/{issue.id}", status_code=303)
