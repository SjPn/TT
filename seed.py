"""Create demo users, project, and sample issues."""

from pathlib import Path

from app.auth import create_user, get_user_by_email
from app.database import Base, SessionLocal, engine
from app.models import IssueStatus, Priority, Project, ProjectMember
from app.services import create_issue, create_project, migrate_legacy_statuses

DATA_DIR = Path(__file__).resolve().parent / "data"


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        migrate_legacy_statuses(db)
        alice = get_user_by_email(db, "alice@example.com")
        if not alice:
            alice = create_user(
                db, email="alice@example.com", name="Alice", password="password"
            )
        bob = get_user_by_email(db, "bob@example.com")
        if not bob:
            bob = create_user(
                db, email="bob@example.com", name="Bob", password="password"
            )

        project = db.query(Project).filter(Project.key == "DEMO").first()
        if not project:
            project = create_project(
                db,
                owner=alice,
                name="Demo Product",
                description="Sample project to explore TaskTracker MVP.",
                key="DEMO",
            )
            if not (
                db.query(ProjectMember)
                .filter(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == bob.id,
                )
                .first()
            ):
                db.add(
                    ProjectMember(
                        project_id=project.id, user_id=bob.id, role="member"
                    )
                )
                db.commit()

            samples = [
                {
                    "title": "Login form rejects valid email",
                    "description": "Steps:\n1. Open /login\n2. Enter valid credentials\n\nExpected: redirect home.\nActual: 400.",
                    "priority": Priority.P1,
                    "status": IssueStatus.OPEN,
                    "labels": "auth, regression",
                    "assignee_id": alice.id,
                },
                {
                    "title": "Add keyboard shortcut for new issue",
                    "description": "Press `N` on list/board to open create dialog.",
                    "priority": Priority.P2,
                    "status": IssueStatus.IN_PROGRESS,
                    "labels": "ux",
                    "assignee_id": bob.id,
                },
                {
                    "title": "Kanban empty-state hint",
                    "description": "Show a short empty state hint per column.",
                    "priority": Priority.P3,
                    "status": IssueStatus.RESOLVED,
                    "labels": "board",
                    "assignee_id": bob.id,
                },
                {
                    "title": "Upload photos when creating a task",
                    "description": "Attach screenshots to new issues.",
                    "priority": Priority.P2,
                    "status": IssueStatus.OPEN,
                    "labels": "backend",
                    "assignee_id": bob.id,
                },
            ]
            for sample in samples:
                create_issue(db, project=project, author=alice, **sample)

        print("Seed complete.")
        print("  alice@example.com / password")
        print("  bob@example.com / password")
        print(f"  Project: {project.key} (id={project.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
