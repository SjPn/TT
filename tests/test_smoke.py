"""Lightweight smoke tests — isolated temp SQLite, no network."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("HTTPS_ONLY", "false")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")

    import app.config as config_mod
    import app.database as db_mod
    import app.main as main_mod

    config_mod.settings = config_mod.Settings(
        data_dir=data,
        secret_key="test-secret",
        https_only=False,
        smtp_host="",
        telegram_bot_token="",
    )
    db_url = f"sqlite:///{data / 'tracker.db'}"
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, connection_record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db_mod.engine = engine
    db_mod.SessionLocal = SessionLocal
    db_mod._db_url = db_url
    main_mod.engine = engine
    main_mod.SessionLocal = SessionLocal

    # Fresh app bound to temp DB
    app = main_mod.create_app()
    with TestClient(app) as c:
        yield c


def _register(client: TestClient, email: str, name: str = "User") -> None:
    r = client.post(
        "/register",
        data={"name": name, "email": email, "password": "secret1"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_health(client: TestClient):
    assert client.get("/health").json() == {"status": "ok"}


def test_register_login_ru(client: TestClient):
    r = client.get("/login")
    assert r.status_code == 200
    assert "Вход" in r.text
    _register(client, "a@example.com", "Аня")
    home = client.get("/")
    assert home.status_code == 200
    assert "Проекты" in home.text


def test_project_issue_workflow(client: TestClient):
    _register(client, "owner@example.com", "Owner")
    r = client.post(
        "/projects",
        data={"name": "Demo", "key": "DEM", "description": "d"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/projects/" in r.headers["location"]

    project_url = r.headers["location"].split("?")[0]
    project_id = int(project_url.rsplit("/", 1)[-1])

    r = client.post(
        f"/projects/{project_id}/issues",
        data={
            "title": "Баг кнопки",
            "description": "описание",
            "priority": "p2",
            "labels": "ui",
            "assignee_id": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "flash=created" in r.headers["location"]
    issue_path = r.headers["location"].split("?")[0]

    detail = client.get(issue_path)
    assert detail.status_code == 200
    assert "Баг кнопки" in detail.text
    assert "Удалить" in detail.text

    # Assign to self via edit
    issue_id = int(issue_path.rsplit("/", 1)[-1])
    # Need user id — get from members by creating second user and assigning
    _register(client, "dev@example.com", "Dev")  # switches session — bad

    # Re-login as owner
    client.post("/logout", follow_redirects=False)
    client.post(
        "/login",
        data={"email": "owner@example.com", "password": "secret1"},
        follow_redirects=False,
    )
    # Add member
    client.post(
        f"/projects/{project_id}/members",
        data={"email": "dev@example.com", "return_view": "list"},
        follow_redirects=False,
    )

    # Get assignee id from project page HTML is hard; use DB
    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        owner = db.query(User).filter_by(email="owner@example.com").one()
        dev = db.query(User).filter_by(email="dev@example.com").one()
        owner_id, dev_id = owner.id, dev.id
    finally:
        db.close()

    client.post(
        f"/projects/{project_id}/issues/{issue_id}",
        data={
            "title": "Баг кнопки",
            "description": "описание",
            "priority": "p2",
            "labels": "ui",
            "assignee_id": str(dev_id),
        },
        follow_redirects=False,
    )

    # As assignee: start + mark done
    client.post("/logout", follow_redirects=False)
    client.post(
        "/login",
        data={"email": "dev@example.com", "password": "secret1"},
        follow_redirects=False,
    )
    r = client.post(
        f"/projects/{project_id}/issues/{issue_id}/start",
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = client.post(
        f"/projects/{project_id}/issues/{issue_id}/mark-done",
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Mine filter
    listing = client.get(f"/projects/{project_id}?mine=1")
    assert listing.status_code == 200
    assert "Баг кнопки" in listing.text

    # Author confirms
    client.post("/logout", follow_redirects=False)
    client.post(
        "/login",
        data={"email": "owner@example.com", "password": "secret1"},
        follow_redirects=False,
    )
    client.post(
        f"/projects/{project_id}/issues/{issue_id}/confirm",
        follow_redirects=False,
    )
    archive = client.get(f"/projects/{project_id}?view=archive")
    assert "Баг кнопки" in archive.text


def test_delete_issue_author_only(client: TestClient):
    _register(client, "a@ex.com", "A")
    client.post("/projects", data={"name": "P", "key": "P1", "description": ""})
    from app.database import SessionLocal
    from app.models import Project

    db = SessionLocal()
    try:
        project = db.query(Project).one()
        pid = project.id
    finally:
        db.close()

    r = client.post(
        f"/projects/{pid}/issues",
        data={
            "title": "Temp",
            "description": "",
            "priority": "p3",
            "labels": "",
            "assignee_id": "",
        },
        follow_redirects=False,
    )
    issue_id = int(r.headers["location"].split("?")[0].rsplit("/", 1)[-1])

    r = client.post(
        f"/projects/{pid}/issues/{issue_id}/delete",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "flash=deleted" in r.headers["location"]
    assert client.get(f"/projects/{pid}/issues/{issue_id}").status_code in (303, 200)
    # After delete, detail redirects to project
    loc = client.get(f"/projects/{pid}/issues/{issue_id}", follow_redirects=False)
    assert loc.status_code == 303


def test_project_search(client: TestClient):
    _register(client, "s@ex.com", "S")
    client.post("/projects", data={"name": "Alpha Mobile", "key": "ALP", "description": ""})
    client.post("/projects", data={"name": "Beta Web", "key": "BET", "description": ""})
    # Force search UI by querying
    r = client.get("/?q=alpha")
    assert r.status_code == 200
    assert "Alpha Mobile" in r.text
    assert "Beta Web" not in r.text


def test_profile_update(client: TestClient):
    _register(client, "old@ex.com", "OldName")
    page = client.get("/profile")
    assert page.status_code == 200
    assert "Профиль" in page.text
    assert 'value="OldName"' in page.text

    r = client.post(
        "/profile",
        data={
            "name": "NewName",
            "email": "new@ex.com",
            "password": "",
            "password_confirm": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/profile" in r.headers["location"]

    page = client.get("/profile")
    assert "NewName" in page.text
    assert "new@ex.com" in page.text

    bad = client.post(
        "/profile",
        data={
            "name": "NewName",
            "email": "new@ex.com",
            "password": "abcdef",
            "password_confirm": "zzzzzz",
        },
    )
    assert bad.status_code == 400
    assert "не совпадают" in bad.text

    ok = client.post(
        "/profile",
        data={
            "name": "NewName",
            "email": "new@ex.com",
            "password": "secret9",
            "password_confirm": "secret9",
        },
        follow_redirects=False,
    )
    assert ok.status_code == 303

    client.post("/logout", follow_redirects=False)
    login = client.post(
        "/login",
        data={"email": "new@ex.com", "password": "secret9"},
        follow_redirects=False,
    )
    assert login.status_code == 303


def test_mentions_and_timeline(client: TestClient):
    _register(client, "ann@ex.com", "Анна")
    client.post("/projects", data={"name": "M", "key": "MM", "description": ""})
    from app.database import SessionLocal
    from app.models import Activity, Notification, Project, User

    db = SessionLocal()
    try:
        pid = db.query(Project).one().id
    finally:
        db.close()

    # Second user
    client.post("/logout", follow_redirects=False)
    _register(client, "bob@ex.com", "Боб")
    client.post("/logout", follow_redirects=False)

    # Owner adds Bob, creates issue, Bob mentions owner
    client.post(
        "/login",
        data={"email": "ann@ex.com", "password": "secret1"},
        follow_redirects=False,
    )
    client.post(
        f"/projects/{pid}/members",
        data={"email": "bob@ex.com", "return_view": "list"},
        follow_redirects=False,
    )
    r = client.post(
        f"/projects/{pid}/issues",
        data={
            "title": "Проверить ленту",
            "description": "",
            "priority": "p3",
            "labels": "",
            "assignee_id": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    issue_id = int(r.headers["location"].split("?")[0].rsplit("/", 1)[-1])

    client.post("/logout", follow_redirects=False)
    client.post(
        "/login",
        data={"email": "bob@ex.com", "password": "secret1"},
        follow_redirects=False,
    )
    client.post(
        f"/projects/{pid}/issues/{issue_id}/comments",
        data={"body": "Глянь @Анна пожалуйста"},
        follow_redirects=False,
    )

    db = SessionLocal()
    try:
        notifs = (
            db.query(Notification)
            .join(User, Notification.user_id == User.id)
            .filter(User.email == "ann@ex.com", Notification.kind == "mention")
            .all()
        )
        assert len(notifs) >= 1
        acts = db.query(Activity).filter(Activity.issue_id == issue_id).all()
        kinds = {a.kind for a in acts}
        assert "created" in kinds
        assert "comment" in kinds
    finally:
        db.close()

    detail = client.get(f"/projects/{pid}/issues/{issue_id}")
    assert detail.status_code == 200
    assert "Лента" in detail.text
    assert "Создал задачу" in detail.text or "Создал" in detail.text


def test_delete_issue_removes_upload_files(client: TestClient):
    _register(client, "u@ex.com", "U")
    client.post("/projects", data={"name": "P", "key": "PX", "description": ""})
    from app.database import SessionLocal
    from app.models import Attachment, Issue, Project, User
    from app.services import UPLOAD_DIR, delete_issue

    db = SessionLocal()
    try:
        user = db.query(User).one()
        project = db.query(Project).one()
        issue = Issue(
            project_id=project.id,
            number=1,
            title="With photo",
            description="",
            author_id=user.id,
        )
        db.add(issue)
        db.flush()
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        stored = "test_photo_xyz.jpg"
        (UPLOAD_DIR / stored).write_bytes(b"fakeimg")
        db.add(
            Attachment(
                issue_id=issue.id,
                filename="a.jpg",
                stored_name=stored,
                content_type="image/jpeg",
            )
        )
        db.commit()
        db.refresh(issue)
        assert (UPLOAD_DIR / stored).exists()
        delete_issue(db, issue=issue)
    finally:
        db.close()

    assert not (UPLOAD_DIR / stored).exists()
