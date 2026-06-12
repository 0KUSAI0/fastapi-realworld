import logging

from pydantic import PostgresDsn, SecretStr

from app.core.settings.app import AppSettings


class TestAppSettings(AppSettings):
    debug: bool = True

    title: str = "Test FastAPI example application"

    secret_key: SecretStr = SecretStr("test_secret")

    database_url: PostgresDsn
    max_connection_count: int = 5
    min_connection_count: int = 5

    ai_comment_moderation_mode: str = "off"
    ai_article_review_on_publish: bool = False
    admin_usernames: list = ["username"]

    logging_level: int = logging.DEBUG

    class Config:
        env_file = None
        validate_assignment = True
