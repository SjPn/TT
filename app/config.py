from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "TaskTracker"
    secret_key: str = "dev-change-me-in-production"
    data_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data")
    database_url: str = ""
    session_cookie: str = "tt_session"
    session_max_age: int = 60 * 60 * 24 * 14  # 14 days
    https_only: bool = False
    public_base_url: str = ""

    # Optional email (all empty = disabled)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    # Optional Telegram bot (empty = disabled)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = self.data_dir / "tracker.db"
        return f"sqlite:///{db_path}"


settings = Settings()
