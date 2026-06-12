from fastapi import Depends

from app.core.config import get_app_settings
from app.core.settings.app import AppSettings
from app.api.dependencies.database import get_repository
from app.db.repositories.articles import ArticlesRepository
from app.services.ai.article_assistant import ArticleAssistantService
from app.services.ai.article_library_qa import ArticleLibraryQAService
from app.services.ai.article_polish import ArticlePolishService
from app.services.ai.article_recommendation import ArticleRecommendationService
from app.services.ai.article_revision import ArticleSuggestionRevisionService
from app.services.ai.comment_moderation import (
    CommentModerationService,
)
from app.services.ai.cross_reranker import CrossReranker
from app.services.ai.embedding_client import EmbeddingClient
from app.services.ai.llm_client import get_llm_client


def get_article_assistant_service(
    settings: AppSettings = Depends(get_app_settings),
) -> ArticleAssistantService:
    return ArticleAssistantService(get_llm_client(settings))


def get_article_polish_service(
    settings: AppSettings = Depends(get_app_settings),
) -> ArticlePolishService:
    return ArticlePolishService(get_llm_client(settings))


def get_article_suggestion_revision_service(
    settings: AppSettings = Depends(get_app_settings),
) -> ArticleSuggestionRevisionService:
    return ArticleSuggestionRevisionService(get_llm_client(settings))


def get_comment_moderation_service(
    settings: AppSettings = Depends(get_app_settings),
) -> CommentModerationService:
    return CommentModerationService(get_llm_client(settings), settings)


def get_article_recommendation_service(
    settings: AppSettings = Depends(get_app_settings),
    articles_repo: ArticlesRepository = Depends(get_repository(ArticlesRepository)),
) -> ArticleRecommendationService:
    llm_client = get_llm_client(settings)
    return ArticleRecommendationService(
        embedding_client=EmbeddingClient(settings),
        articles_repo=articles_repo,
        cross_reranker=CrossReranker(llm_client),
    )


def get_article_library_qa_service(
    settings: AppSettings = Depends(get_app_settings),
    recommendation_service: ArticleRecommendationService = Depends(
        get_article_recommendation_service,
    ),
) -> ArticleLibraryQAService:
    return ArticleLibraryQAService(
        llm_client=get_llm_client(settings),
        recommendation_service=recommendation_service,
    )
