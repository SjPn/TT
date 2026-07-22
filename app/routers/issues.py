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
    Activity,
    Comment,
    Issue,
    IssueStatus,
    Priority,
    Project,
    User,
)
from app.services import (
    CommentError,
    WorkflowError,
    add_comment,
    build_comment_seen_map,
    confirm_issue_done,
    create_issue,
    delete_comment_attachments,
    delete_issue,
    issues_by_status,
    list_issue_visits,
    list_issues,
    mark_issue_done,
    next_step_hint,
    normalize_labels,
    notify_assignment,
    save_images,
    save_issue_images,
    start_issue,
    touch_issue_visit,
    update_comment,
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
    role: str | None = Query(None),
    mine: str | None = Query(None),
    view: str = Query("list"),
    member_ok: str | None = Query(None),
    member_error: str | None = Query(None),
    flash: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    members = project_members(db, project)
    # role: assigned | created; legacy mine=1 → assigned
    filter_role = (role or "").strip().lower()
    if not filter_role and mine in ("1", "true", "yes", "on"):
        filter_role = "assigned"
    assignee_filter = user.id if filter_role == "assigned" else None
    author_filter = user.id if filter_role == "created" else None
    ctx = _common_ctx(project, user, members)
    ctx.update(
        {
            "q": q or "",
            "filter_status": status or "",
            "filter_priority": priority or "",
            "filter_role": filter_role,
            "view": view,
            "member_ok": member_ok,
            "member_error": member_error,
            "flash": flash,
        }
    )
    if view == "board":
        ctx["columns"] = issues_by_status(db, project)
        return templates.TemplateResponse(request, "issues/board.html", ctx)

    if view == "archive":
        ctx["issues"] = list_issues(
            db,
            project,
            q=q,
            priority=priority,
            assignee_id=assignee_filter,
            author_id=author_filter,
            archived=True,
        )
        return templates.TemplateResponse(request, "issues/archive.html", ctx)

    ctx["issues"] = list_issues(
        db,
        project,
        q=q,
        status=status,
        priority=priority,
        assignee_id=assignee_filter,
        author_id=author_filter,
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
    if assignee:
        notify_assignment(db, issue=issue, assignee_id=assignee, actor=user)
    return RedirectResponse(
        f"/projects/{project.id}/issues/{issue.id}?flash=created",
        status_code=303,
    )


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
    flash: str | None = Query(None),
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
            joinedload(Issue.activities).joinedload(Activity.actor),
            joinedload(Issue.activities).joinedload(Activity.comment).joinedload(Comment.attachments),
            joinedload(Issue.activities).joinedload(Activity.comment).joinedload(Comment.author),
            joinedload(Issue.activities).joinedload(Activity.comment).joinedload(Comment.reply_to).joinedload(Comment.author),
        )
        .filter(Issue.id == issue_id, Issue.project_id == project.id)
        .first()
    )
    if not issue:
        return RedirectResponse(f"/projects/{project.id}", status_code=303)
    touch_issue_visit(db, user=user, issue=issue)
    members = project_members(db, project)
    timeline = sorted(
        issue.activities,
        key=lambda a: (a.created_at is None, a.created_at, a.id),
    )
    visits = list_issue_visits(db, issue)
    comment_seen = build_comment_seen_map(issue=issue, viewer=user, visits=visits)
    return templates.TemplateResponse(
        request,
        "issues/detail.html",
        {
            **_common_ctx(project, user, members),
            "issue": issue,
            "flash": flash,
            "timeline": timeline,
            "comment_seen": comment_seen,
            "next_step": next_step_hint(issue=issue, user=user),
            "can_start": (
                issue.assignee_id == user.id and issue.status == IssueStatus.OPEN
            ),
            "can_mark_done": (
                issue.assignee_id == user.id
                and issue.status
                in (IssueStatus.OPEN, IssueStatus.IN_PROGRESS)
            ),
            "can_confirm": (
                issue.author_id == user.id
                and issue.status == IssueStatus.PENDING_CONFIRM
            ),
            "can_delete": issue.author_id == user.id,
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
    new_assignee = int(assignee_id) if assignee_id.strip().isdigit() else None
    prev_assignee = issue.assignee_id
    issue.assignee_id = new_assignee
    db.add(issue)
    db.commit()
    if new_assignee and new_assignee != prev_assignee:
        notify_assignment(db, issue=issue, assignee_id=new_assignee, actor=user)
    return RedirectResponse(
        f"/projects/{project.id}/issues/{issue.id}?flash=saved",
        status_code=303,
    )


@router.post("/projects/{project_id}/issues/{issue_id}/delete")
def delete_issue_route(
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
    delete_issue(db, issue=issue)
    return RedirectResponse(
        f"/projects/{project.id}?flash=deleted",
        status_code=303,
    )


@router.post("/projects/{project_id}/issues/{issue_id}/start")
def start_issue_route(
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
        start_issue(db, issue=issue, user=user)
    except WorkflowError:
        pass
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
    # Board: assignee moves open ↔ in_progress only
    allowed = {IssueStatus.OPEN, IssueStatus.IN_PROGRESS}
    if (
        issue.assignee_id == user.id
        and issue.status in allowed
        and status in allowed
    ):
        update_issue_status(db, issue, status, actor=user)
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
    reply_to_id: str = Form(""),
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
    reply_id: int | None = None
    if reply_to_id.strip().isdigit():
        candidate = int(reply_to_id.strip())
        parent = db.get(Comment, candidate)
        if parent and parent.issue_id == issue.id:
            reply_id = candidate
    comment = add_comment(
        db,
        issue=issue,
        author=user,
        body=text or " ",
        members=project_members(db, project),
        reply_to_id=reply_id,
    )
    if has_photos:
        await save_images(db, issue=issue, files=list(photos), comment=comment)
    return RedirectResponse(f"/projects/{project.id}/issues/{issue.id}", status_code=303)


@router.post(
    "/projects/{project_id}/issues/{issue_id}/comments/{comment_id}/edit",
    response_class=HTMLResponse,
)
async def edit_comment(
    project_id: int,
    issue_id: int,
    comment_id: int,
    body: str = Form(""),
    remove_attachment_ids: Annotated[list[int], Form()] = [],
    photos: Annotated[list[UploadFile], File()] = [],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    project = require_project_access(db, user, project_id)
    issue = db.get(Issue, issue_id)
    if not issue or issue.project_id != project.id:
        return RedirectResponse(f"/projects/{project.id}", status_code=303)
    comment = (
        db.query(Comment)
        .options(joinedload(Comment.attachments))
        .filter(Comment.id == comment_id)
        .first()
    )
    if not comment or comment.issue_id != issue.id:
        return RedirectResponse(f"/projects/{project.id}/issues/{issue.id}", status_code=303)
    if comment.author_id != user.id or issue.is_archived:
        return RedirectResponse(f"/projects/{project.id}/issues/{issue.id}", status_code=303)

    has_photos = any(p.filename for p in photos) if photos else False
    remove_ids = [i for i in remove_attachment_ids if isinstance(i, int)]
    current_ids = {att.id for att in comment.attachments}
    remaining = len(current_ids - set(remove_ids))
    if not body.strip() and remaining == 0 and not has_photos:
        return RedirectResponse(f"/projects/{project.id}/issues/{issue.id}", status_code=303)

    try:
        if remove_ids:
            delete_comment_attachments(
                db,
                comment=comment,
                user=user,
                attachment_ids=remove_ids,
            )
        update_comment(
            db,
            issue=issue,
            comment=comment,
            user=user,
            body=body,
            has_new_photos=has_photos,
        )
        if has_photos:
            await save_images(db, issue=issue, files=list(photos), comment=comment)
    except CommentError:
        pass
    return RedirectResponse(f"/projects/{project.id}/issues/{issue.id}", status_code=303)
