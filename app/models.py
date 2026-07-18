from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class IssueStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING_CONFIRM = "pending_confirm"
    RESOLVED = "resolved"


class Priority(StrEnum):
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"
    P4 = "p4"


# Active board/list (not archive)
BOARD_STATUSES = [
    IssueStatus.OPEN,
    IssueStatus.IN_PROGRESS,
    IssueStatus.PENDING_CONFIRM,
]
STATUS_ORDER = BOARD_STATUSES
STATUS_LABELS = {
    IssueStatus.OPEN: "Открыта",
    IssueStatus.IN_PROGRESS: "В работе",
    IssueStatus.PENDING_CONFIRM: "На подтверждении",
    IssueStatus.RESOLVED: "Решено",
}
PRIORITY_LABELS = {
    Priority.P1: "P1 · Critical",
    Priority.P2: "P2 · High",
    Priority.P3: "P3 · Medium",
    Priority.P4: "P4 · Low",
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owned_projects: Mapped[list["Project"]] = relationship(back_populates="owner")
    assigned_issues: Mapped[list["Issue"]] = relationship(
        back_populates="assignee", foreign_keys="Issue.assignee_id"
    )
    authored_issues: Mapped[list["Issue"]] = relationship(
        back_populates="author", foreign_keys="Issue.author_id"
    )
    comments: Mapped[list["Comment"]] = relationship(back_populates="author")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    issue_counter: Mapped[int] = mapped_column(Integer, default=0)

    owner: Mapped["User"] = relationship(back_populates="owned_projects")
    issues: Mapped[list["Issue"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32), default="member")

    project: Mapped["Project"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship()


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_project_issue_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    issue_type: Mapped[str] = mapped_column(String(16), default="task")
    status: Mapped[str] = mapped_column(String(32), default=IssueStatus.OPEN, index=True)
    priority: Mapped[str] = mapped_column(String(8), default=Priority.P3, index=True)
    labels: Mapped[str] = mapped_column(String(500), default="")
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    board_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="issues")
    author: Mapped["User"] = relationship(back_populates="authored_issues", foreign_keys=[author_id])
    assignee: Mapped[Optional["User"]] = relationship(
        back_populates="assigned_issues", foreign_keys=[assignee_id]
    )
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="issue", cascade="all, delete-orphan", order_by="Comment.created_at"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="issue",
        cascade="all, delete-orphan",
        order_by="Attachment.created_at",
        primaryjoin="and_(Issue.id==Attachment.issue_id, Attachment.comment_id==None)",
        foreign_keys="Attachment.issue_id",
    )

    @property
    def key(self) -> str:
        return f"{self.project.key}-{self.number}"

    @property
    def label_list(self) -> list[str]:
        if not self.labels.strip():
            return []
        return [part.strip() for part in self.labels.split(",") if part.strip()]

    @property
    def is_archived(self) -> bool:
        return self.status == IssueStatus.RESOLVED


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    issue: Mapped["Issue"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship(back_populates="comments")
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="comment", cascade="all, delete-orphan", order_by="Attachment.created_at"
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    comment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(120), default="image/jpeg")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    issue: Mapped["Issue"] = relationship(back_populates="attachments")
    comment: Mapped[Optional["Comment"]] = relationship(back_populates="attachments")
