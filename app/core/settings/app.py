import logging
import sys
from enum import Enum
from typing import Any, Dict, List, Tuple

from loguru import logger
from pydantic import PostgresDsn, SecretStr

from app.core.logging import InterceptHandler
from app.core.settings.base import BaseAppSettings


class CommentModerationMode(str, Enum):
    off = "off"
    log = "log"
    block = "block"


class AppSettings(BaseAppSettings):
    debug: bool = False
    docs_url: str = "/docs"
    openapi_prefix: str = ""
    openapi_url: str = "/openapi.json"
    redoc_url: str = "/redoc"
    title: str = "FastAPI example application"
    version: str = "0.0.0"

    database_url: PostgresDsn
    max_connection_count: int = 10
    min_connection_count: int = 10

    secret_key: SecretStr

    api_prefix: str = "/api"

    jwt_token_prefix: str = "Token"
    admin_usernames: List[str] = ["admin"]

    allowed_hosts: List[str] = ["*"]

    llm_base_url: str = "http://127.0.0.1:8000/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "qwen3-8b"
    llm_timeout_seconds: int = 30

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimensions: int = 384
    embedding_cache_folder: str = ""
    embedding_allow_download: bool = False
    embedding_fallback_enabled: bool = True

    ai_comment_moderation_mode: CommentModerationMode = CommentModerationMode.off
    ai_article_review_on_publish: bool = False
    ai_article_min_content_score: int = 50

    logging_level: int = logging.INFO
    loggers: Tuple[str, str] = ("uvicorn.asgi", "uvicorn.access")

    class Config:
        validate_assignment = True

    @property
    def fastapi_kwargs(self) -> Dict[str, Any]:
        return {
            "debug": self.debug,
            "docs_url": self.docs_url,
            "openapi_prefix": self.openapi_prefix,
            "openapi_url": self.openapi_url,
            "redoc_url": self.redoc_url,
            "title": self.title,
            "version": self.version,
        }

    def configure_logging(self) -> None:
        logging.getLogger().handlers = [InterceptHandler()]
        for logger_name in self.loggers:
            logging_logger = logging.getLogger(logger_name)
            logging_logger.handlers = [InterceptHandler(level=self.logging_level)]

        logger.configure(handlers=[{"sink": sys.stderr, "level": self.logging_level}])
