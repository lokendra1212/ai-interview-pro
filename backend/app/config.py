from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ENV = BACKEND_DIR.parent / ".env"

class Settings(BaseSettings):
    jwt_secret: str = "local-dev-change-me"
    database_url: str = "sqlite:///./ai_interview_pro.db"
    cors_origins: str = "http://localhost:5173"
    max_upload_mb: int = 8
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    model_config = SettingsConfigDict(env_file=str(PROJECT_ENV), extra="ignore", case_sensitive=False)

    @field_validator("database_url")
    @classmethod
    def anchor_sqlite_path(cls, value: str) -> str:
        if value in {"sqlite://", "sqlite:///:memory:"} or not value.startswith("sqlite:///") or value.startswith("sqlite:////"):
            return value
        path = Path(value.removeprefix("sqlite:///"))
        if not path.is_absolute():
            path = BACKEND_DIR / path
        return f"sqlite:///{path.resolve().as_posix()}"

settings = Settings()
