import bcrypt
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User

serializer = URLSafeTimedSerializer(settings.secret_key, salt="tt-session")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_session_token(user_id: int) -> str:
    return serializer.dumps({"uid": user_id})


def parse_session_token(token: str) -> int | None:
    try:
        data = serializer.loads(token, max_age=settings.session_max_age)
        return int(data["uid"])
    except (BadSignature, KeyError, TypeError, ValueError):
        return None


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.lower().strip()).first()


def create_user(db: Session, *, email: str, name: str, password: str) -> User:
    user = User(
        email=email.lower().strip(),
        name=name.strip(),
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_profile(
    db: Session,
    *,
    user: User,
    name: str,
    email: str,
    password: str | None = None,
) -> User:
    user.name = name.strip()
    user.email = email.lower().strip()
    if password:
        user.password_hash = hash_password(password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
