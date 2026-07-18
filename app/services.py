from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.auth import get_user_by_email
from app.config import settings
from app.deps import slugify_key
from app.models import (
    STATUS_LABELS,
    Activity,
    Attachment,
    BOARD_STATUSES,
    Comment,
    Issue,
    IssueStatus,
    Notification,
    Priority,
    Project,
    ProjectMember,
    User,
)

UPLOAD_DIR = Path(settings.data_dir) / "uploads"
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MENTION_RE = re.compile(r"@([^\s@]+(?:\s+[^\s@]+)?)")


class MemberError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class WorkflowError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def unique_project_key(db: Session, base: str) -> str:
    key = base[:8]
    candidate = key
    n = 2
    while db.query(Project).filter(Project.key == candidate).first():
        suffix = str(n)
        candidate = f"{key[: 8 - len(suffix)]}{suffix}"
        n += 1
    return candidate


def create_project(
    db: Session,
    *,
    owner: User,
    name: str,
    description: str = "",
    key: str | None = None,
) -> Project:
    base = (key or slugify_key(name)).upper()[:8]
    project = Project(
        key=unique_project_key(db, base),
        name=name.strip(),
        description=description.strip(),
        owner_id=owner.id,
        issue_counter=0,
    )
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=owner.id, role="owner"))
    db.commit()
    db.refresh(project)
    return project


def add_project_member(db: Session, *, project: Project, email: str) -> User:
    user = get_user_by_email(db, email)
    if not user:
        raise MemberError("Нет пользователя с таким email")
    if user.id == project.owner_id:
        raise MemberError("Этот пользователь уже владелец проекта")
    existing = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
        .first()
    )
    if existing:
        raise MemberError("Пользователь уже в проекте")
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="member"))
    db.commit()
    notify(
        db,
        user_id=user.id,
        kind="project_added",
        title=f"Вас добавили в проект {project.name}",
        body=f"Ключ проекта: {project.key}",
        link=f"/projects/{project.id}",
    )
    return user


def update_project(
    db: Session,
    *,
    project: Project,
    name: str,
    description: str = "",
) -> Project:
    project.name = name.strip()
    project.description = description.strip()
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _unlink_uploads(stored_names: list[str]) -> None:
    for name in stored_names:
        if not name or "/" in name or "\\" in name or ".." in name:
            continue
        path = UPLOAD_DIR / name
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def delete_project(db: Session, *, project: Project) -> None:
    stored = [
        row[0]
        for row in db.query(Attachment.stored_name)
        .join(Issue, Attachment.issue_id == Issue.id)
        .filter(Issue.project_id == project.id)
        .all()
    ]
    db.delete(project)
    db.commit()
    _unlink_uploads(stored)


def notify(
    db: Session,
    *,
    user_id: int,
    kind: str,
    title: str,
    body: str = "",
    link: str = "",
) -> Notification:
    item = Notification(
        user_id=user_id,
        kind=kind,
        title=title,
        body=body,
        link=link,
        is_read=False,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    user = db.get(User, user_id)
    if user:
        from app.notify_channels import push_external

        push_external(email=user.email, title=title, body=body, link=link)
    return item


def notify_assignment(
    db: Session,
    *,
    issue: Issue,
    assignee_id: int | None,
    actor: User,
) -> None:
    if not assignee_id or assignee_id == actor.id:
        return
    notify(
        db,
        user_id=assignee_id,
        kind="issue_assigned",
        title=f"Вам назначена задача: {issue.title}",
        body=f"{issue.key} · назначил {actor.name}",
        link=f"/projects/{issue.project_id}/issues/{issue.id}",
    )
    assignee = db.get(User, assignee_id)
    who = assignee.name if assignee else "исполнителя"
    log_activity(
        db,
        issue=issue,
        actor=actor,
        kind="assign",
        body=f"Назначил: {who}",
        commit=True,
    )


def log_activity(
    db: Session,
    *,
    issue: Issue,
    actor: User | None,
    kind: str,
    body: str = "",
    comment_id: int | None = None,
    commit: bool = True,
) -> Activity:
    item = Activity(
        issue_id=issue.id,
        actor_id=actor.id if actor else None,
        kind=kind,
        body=body[:500],
        comment_id=comment_id,
    )
    db.add(item)
    if commit:
        db.commit()
        db.refresh(item)
    else:
        db.flush()
    return item


def next_step_hint(*, issue: Issue, user: User) -> str | None:
    self_assigned = issue.assignee_id is not None and issue.assignee_id == issue.author_id

    if issue.status == IssueStatus.RESOLVED:
        return "Задача решена и в архиве."
    if issue.status == IssueStatus.PENDING_CONFIRM:
        if issue.author_id == user.id:
            return "Проверьте результат и подтвердите."
        return "Ждём подтверждения автора."
    if issue.assignee_id is None:
        if issue.author_id == user.id:
            return "Сначала назначьте исполнителя."
        return "Исполнитель ещё не назначен."
    if issue.assignee_id == user.id:
        if issue.status == IssueStatus.OPEN:
            return "Ваш ход — начните или сразу отметьте готовой."
        if issue.status == IssueStatus.IN_PROGRESS:
            if self_assigned or issue.author_id == user.id:
                return "Когда готово — отметьте, задача закроется."
            return "Когда готово — отметьте. Автор подтвердит."
    if issue.author_id == user.id and issue.status == IssueStatus.IN_PROGRESS:
        name = issue.assignee.name if issue.assignee else "исполнитель"
        return f"В работе у {name}. Ждите отметки «готово»."
    if issue.assignee and issue.status == IssueStatus.OPEN:
        return f"Ждём, пока {issue.assignee.name} возьмёт задачу."
    return None


def resolve_mentions(text: str, members: list[User]) -> list[User]:
    if not text or not members:
        return []
    by_name = {m.name.lower(): m for m in members}
    by_email = {m.email.lower(): m for m in members}
    # Longest names first for multi-word matches
    names = sorted({m.name for m in members}, key=len, reverse=True)
    found: dict[int, User] = {}
    lower = text.lower()
    for name in names:
        needle = f"@{name.lower()}"
        if needle in lower:
            user = by_name.get(name.lower())
            if user:
                found[user.id] = user
    for email, user in by_email.items():
        if f"@{email}" in lower:
            found[user.id] = user
    # Also bare @FirstName token
    for token in re.findall(r"@([\w.\-]+)", text):
        key = token.lower()
        if key in by_email:
            found[by_email[key].id] = by_email[key]
            continue
        for m in members:
            first = m.name.split()[0].lower() if m.name else ""
            if key == first or key == m.name.lower():
                found[m.id] = m
    return list(found.values())


def notify_mentions(
    db: Session,
    *,
    issue: Issue,
    author: User,
    members: list[User],
    text: str,
) -> None:
    for mentioned in resolve_mentions(text, members):
        if mentioned.id == author.id:
            continue
        notify(
            db,
            user_id=mentioned.id,
            kind="mention",
            title=f"{author.name} упомянул вас",
            body=f"{issue.key}: {issue.title}",
            link=f"/projects/{issue.project_id}/issues/{issue.id}",
        )


def list_notifications(db: Session, user: User, *, limit: int = 20) -> list[Notification]:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )


def unread_notification_count(db: Session, user: User) -> int:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .count()
    )


def mark_notifications_read(db: Session, user: User, notification_id: int | None = None) -> None:
    q = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read.is_(False)
    )
    if notification_id is not None:
        q = q.filter(Notification.id == notification_id)
    q.update({Notification.is_read: True}, synchronize_session=False)
    db.commit()


def next_issue_number(db: Session, project: Project) -> int:
    project.issue_counter += 1
    db.add(project)
    return project.issue_counter


def create_issue(
    db: Session,
    *,
    project: Project,
    author: User,
    title: str,
    description: str = "",
    priority: str = Priority.P3,
    status: str = IssueStatus.OPEN,
    labels: str = "",
    assignee_id: int | None = None,
) -> Issue:
    number = next_issue_number(db, project)
    max_order = (
        db.query(Issue)
        .filter(Issue.project_id == project.id, Issue.status == status)
        .count()
    )
    issue = Issue(
        project_id=project.id,
        number=number,
        title=title.strip(),
        description=description.strip(),
        issue_type="task",
        priority=priority,
        status=status,
        labels=normalize_labels(labels),
        author_id=author.id,
        assignee_id=assignee_id,
        board_order=max_order,
    )
    db.add(issue)
    db.flush()
    log_activity(
        db,
        issue=issue,
        actor=author,
        kind="created",
        body="Создал задачу",
        commit=False,
    )
    db.commit()
    db.refresh(issue)
    return issue


def normalize_labels(raw: str) -> str:
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        key = part.lower()
        if key not in seen:
            seen.add(key)
            result.append(part)
    return ", ".join(result)


def list_issues(
    db: Session,
    project: Project,
    *,
    q: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assignee_id: int | None = None,
    archived: bool = False,
) -> list[Issue]:
    query = (
        db.query(Issue)
        .options(
            joinedload(Issue.assignee),
            joinedload(Issue.author),
            joinedload(Issue.attachments),
        )
        .filter(Issue.project_id == project.id)
    )
    if archived:
        query = query.filter(Issue.status == IssueStatus.RESOLVED)
    elif status:
        query = query.filter(Issue.status == status)
    else:
        query = query.filter(Issue.status != IssueStatus.RESOLVED)

    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Issue.title.ilike(like),
                Issue.description.ilike(like),
                Issue.labels.ilike(like),
            )
        )
    if priority:
        query = query.filter(Issue.priority == priority)
    if assignee_id:
        query = query.filter(Issue.assignee_id == assignee_id)

    priority_rank = {
        Priority.P1: 0,
        Priority.P2: 1,
        Priority.P3: 2,
        Priority.P4: 3,
    }
    issues = query.all()
    issues.sort(
        key=lambda i: (
            priority_rank.get(i.priority, 9),
            -i.number,
        )
    )
    return issues


def issues_by_status(db: Session, project: Project) -> dict[str, list[Issue]]:
    issues = (
        db.query(Issue)
        .options(joinedload(Issue.assignee))
        .filter(
            Issue.project_id == project.id,
            Issue.status.in_([s.value for s in BOARD_STATUSES]),
        )
        .order_by(Issue.board_order.asc(), Issue.number.desc())
        .all()
    )
    buckets: dict[str, list[Issue]] = {s.value: [] for s in BOARD_STATUSES}
    for issue in issues:
        buckets.setdefault(issue.status, []).append(issue)
    return buckets


def update_issue_status(
    db: Session,
    issue: Issue,
    status: str,
    *,
    actor: User | None = None,
) -> Issue:
    prev = issue.status
    if prev == status:
        return issue
    issue.status = status
    count = (
        db.query(Issue)
        .filter(Issue.project_id == issue.project_id, Issue.status == status)
        .count()
    )
    issue.board_order = count
    db.add(issue)
    db.flush()
    from_label = STATUS_LABELS.get(prev, prev)
    to_label = STATUS_LABELS.get(status, status)
    log_activity(
        db,
        issue=issue,
        actor=actor,
        kind="status",
        body=f"{from_label} → {to_label}",
        commit=False,
    )
    db.commit()
    db.refresh(issue)
    return issue


def mark_issue_done(db: Session, *, issue: Issue, user: User) -> Issue:
    if issue.status == IssueStatus.RESOLVED:
        raise WorkflowError("Задача уже в архиве")
    if issue.assignee_id is None:
        raise WorkflowError("Сначала назначьте исполнителя")
    if issue.assignee_id != user.id:
        raise WorkflowError("Отметить выполнение может только назначенный")
    if issue.status == IssueStatus.PENDING_CONFIRM:
        raise WorkflowError("Уже ожидает подтверждения автора")
    # Author working on own task — no need to confirm yourself
    if issue.author_id == user.id:
        return update_issue_status(db, issue, IssueStatus.RESOLVED, actor=user)
    return update_issue_status(db, issue, IssueStatus.PENDING_CONFIRM, actor=user)


def confirm_issue_done(db: Session, *, issue: Issue, user: User) -> Issue:
    if issue.author_id != user.id:
        raise WorkflowError("Подтвердить может только автор задачи")
    if issue.status != IssueStatus.PENDING_CONFIRM:
        raise WorkflowError("Задача ещё не отмечена выполненной")
    return update_issue_status(db, issue, IssueStatus.RESOLVED, actor=user)


def add_comment(
    db: Session,
    *,
    issue: Issue,
    author: User,
    body: str,
    members: list[User] | None = None,
) -> Comment:
    comment = Comment(issue_id=issue.id, author_id=author.id, body=body.strip())
    db.add(comment)
    db.flush()
    preview = body.strip()
    if len(preview) > 120:
        preview = preview[:117] + "…"
    log_activity(
        db,
        issue=issue,
        actor=author,
        kind="comment",
        body=preview or "Прикрепил фото",
        comment_id=comment.id,
        commit=False,
    )
    db.commit()
    db.refresh(comment)
    if members and body.strip():
        notify_mentions(db, issue=issue, author=author, members=members, text=body)
    return comment


async def save_images(
    db: Session,
    *,
    issue: Issue,
    files: list[UploadFile],
    comment: Comment | None = None,
) -> list[Attachment]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[Attachment] = []
    for upload in files:
        if not upload or not upload.filename:
            continue
        content_type = (upload.content_type or "").lower()
        if content_type not in ALLOWED_IMAGE_TYPES:
            continue
        data = await upload.read()
        if not data or len(data) > MAX_IMAGE_BYTES:
            continue
        ext = Path(upload.filename).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            ext = {
                "image/jpeg": ".jpg",
                "image/jpg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
            }.get(content_type, ".jpg")
        stored = f"{uuid.uuid4().hex}{ext}"
        (UPLOAD_DIR / stored).write_bytes(data)
        att = Attachment(
            issue_id=issue.id,
            comment_id=comment.id if comment else None,
            filename=upload.filename,
            stored_name=stored,
            content_type=content_type,
        )
        db.add(att)
        saved.append(att)
    if saved:
        db.commit()
        for att in saved:
            db.refresh(att)
    return saved


async def save_issue_images(
    db: Session, *, issue: Issue, files: list[UploadFile]
) -> list[Attachment]:
    return await save_images(db, issue=issue, files=files)


def delete_issue(db: Session, *, issue: Issue) -> int:
    project_id = issue.project_id
    stored = [
        row[0]
        for row in db.query(Attachment.stored_name)
        .filter(Attachment.issue_id == issue.id)
        .all()
    ]
    db.delete(issue)
    db.commit()
    _unlink_uploads(stored)
    return project_id


def start_issue(db: Session, *, issue: Issue, user: User) -> Issue:
    if issue.assignee_id != user.id:
        raise WorkflowError("В работу может взять только исполнитель")
    if issue.status == IssueStatus.IN_PROGRESS:
        return issue
    if issue.status != IssueStatus.OPEN:
        raise WorkflowError("Нельзя взять эту задачу в работу")
    return update_issue_status(db, issue, IssueStatus.IN_PROGRESS, actor=user)


def migrate_backfill_activities(db: Session) -> None:
    """One-time: seed timeline from existing comments if activities table is empty."""
    if db.query(Activity).first() is not None:
        return
    for issue in db.query(Issue).all():
        db.add(
            Activity(
                issue_id=issue.id,
                actor_id=issue.author_id,
                kind="created",
                body="Создал задачу",
                created_at=issue.created_at,
            )
        )
        for comment in (
            db.query(Comment)
            .filter(Comment.issue_id == issue.id)
            .order_by(Comment.created_at.asc())
            .all()
        ):
            preview = (comment.body or "").strip()
            if len(preview) > 120:
                preview = preview[:117] + "…"
            db.add(
                Activity(
                    issue_id=issue.id,
                    actor_id=comment.author_id,
                    kind="comment",
                    body=preview or "Прикрепил фото",
                    comment_id=comment.id,
                    created_at=comment.created_at,
                )
            )
    db.commit()


def migrate_legacy_statuses(db: Session) -> None:
    """Map old 'done' status to resolved archive."""
    updated = (
        db.query(Issue)
        .filter(Issue.status == "done")
        .update({Issue.status: IssueStatus.RESOLVED}, synchronize_session=False)
    )
    if updated:
        db.commit()


def migrate_attachment_comment_id(engine) -> None:
    """Add comment_id column to attachments if missing (SQLite)."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "attachments" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("attachments")}
    if "comment_id" in cols:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE attachments ADD COLUMN comment_id INTEGER"))
