import os
from typing import List

import pytest
from asyncpg.pool import Pool
from fastapi import Depends, FastAPI
from httpx import AsyncClient
from starlette import status

from app.api.dependencies.ai import (
    get_article_assistant_service,
    get_article_library_qa_service,
)
from app.api.dependencies.database import get_repository
from app.core.settings.test import TestAppSettings as AppSettingsForRealAITests
from app.db.repositories.articles import ArticlesRepository
from app.models.schemas.articles import (
    ArticleAIAnalysisInResponse,
    ArticleLibraryQAInResponse,
)
from app.services.ai.article_assistant import ArticleAssistantService
from app.services.ai.article_library_qa import ArticleLibraryQAService
from app.services.ai.article_recommendation import ArticleRecommendationService
from app.services.ai.cross_reranker import CrossReranker
from app.services.ai.embedding_client import EmbeddingClient
from app.services.ai.llm_client import LLMClient

from dotenv import load_dotenv

load_dotenv()

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("RUN_REAL_AI_TESTS") != "1",
        reason="set RUN_REAL_AI_TESTS=1 to call the configured real LLM endpoint",
    ),
]


def _real_ai_settings() -> AppSettingsForRealAITests:
    return AppSettingsForRealAITests(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:15432/rwtest",
        ),
        llm_base_url=os.getenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", "qwen3-8b"),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        embedding_model=os.getenv("EMBEDDING_MODEL", "sentence-transformers/not-cached"),
        embedding_dimensions=384,
        embedding_allow_download=False,
        embedding_fallback_enabled=True,
    )


async def _close_clients(clients: List[LLMClient]) -> None:
    for client in clients:
        await client.aclose()


async def test_article_analysis_api_uses_real_llm(
    app: FastAPI,
    authorized_client: AsyncClient,
) -> None:
    settings = _real_ai_settings()
    clients: List[LLMClient] = []

    def build_article_assistant_service() -> ArticleAssistantService:
        client = LLMClient(settings)
        clients.append(client)
        return ArticleAssistantService(client)

    app.dependency_overrides[
        get_article_assistant_service
    ] = build_article_assistant_service
    try:
        response = await authorized_client.post(
            app.url_path_for("articles:analyze-article-with-ai"),
            json={
                "article": {
                    "title": "城市散步与注意力恢复",
                    "description": "记录通勤、街区散步和工作专注力之间的关系。",
                    "body": "城市散步让早晨的工作节奏更稳定。" * 20,
                    "tagList": ["城市生活", "注意力"],
                },
            },
        )
    finally:
        app.dependency_overrides.pop(get_article_assistant_service)
        await _close_clients(clients)

    assert response.status_code == status.HTTP_200_OK
    analysis = ArticleAIAnalysisInResponse(**response.json()).analysis
    assert analysis.model == settings.llm_model
    assert analysis.summary
    assert analysis.suggestions
    assert 0 <= analysis.content_score <= 100


async def test_article_library_qa_api_uses_real_llm(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_user,
    pool: Pool,
) -> None:
    settings = _real_ai_settings()
    clients: List[LLMClient] = []
    async with pool.acquire() as connection:
        await ArticlesRepository(connection).create_article(
            slug="city-walk-focus-real-ai",
            title="城市散步与注意力恢复",
            description="讨论城市生活、散步和工作专注力之间的关系。",
            body="连续早起散步后，工作日前半程的注意力更加稳定，也更容易进入状态。" * 12,
            author=test_user,
            tags=["城市生活", "散步", "注意力"],
        )

    def build_recommendation_service(
        articles_repo: ArticlesRepository = Depends(get_repository(ArticlesRepository)),
    ) -> ArticleRecommendationService:
        rerank_client = LLMClient(settings)
        clients.append(rerank_client)
        return ArticleRecommendationService(
            embedding_client=EmbeddingClient(settings),
            articles_repo=articles_repo,
            cross_reranker=CrossReranker(rerank_client),
        )

    def build_article_library_qa_service(
        recommendation_service: ArticleRecommendationService = Depends(
            build_recommendation_service,
        ),
    ) -> ArticleLibraryQAService:
        qa_client = LLMClient(settings)
        clients.append(qa_client)
        return ArticleLibraryQAService(
            llm_client=qa_client,
            recommendation_service=recommendation_service,
        )

    app.dependency_overrides[
        get_article_library_qa_service
    ] = build_article_library_qa_service
    try:
        response = await authorized_client.post(
            app.url_path_for("articles:ask-article-library"),
            json={"question": "有没有关于城市散步和注意力恢复的文章？", "limit": 3},
        )
    finally:
        app.dependency_overrides.pop(get_article_library_qa_service)
        await _close_clients(clients)

    assert response.status_code == status.HTTP_200_OK
    result = ArticleLibraryQAInResponse(**response.json()).result
    assert result.model == settings.llm_model
    assert result.answer
    assert result.sources
    assert result.sources[0].article.slug == "city-walk-focus-real-ai"
    assert "city-walk-focus-real-ai" in result.citations
