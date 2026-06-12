import os

import pytest

from app.core.settings.app import AppSettings
from app.models.domain.articles import Article
from app.models.domain.profiles import Profile
from app.models.domain.users import User
from app.models.schemas.articles import ArticleInCreate
from app.services.ai.article_assistant import ArticleAssistantService
from app.services.ai.comment_moderation import CommentModerationService
from app.services.ai.cross_reranker import CrossReranker
from app.services.ai.llm_client import LLMClient
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REAL_AI_TESTS") != "1",
    reason="set RUN_REAL_AI_TESTS=1 to call the configured real LLM endpoint",
)

def _real_ai_settings() -> AppSettings:
    return AppSettings(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:15432/rwtest",
        ),
        secret_key=os.getenv("SECRET_KEY", "secret"),
        llm_base_url=os.getenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", "qwen3-8b"),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        ai_comment_moderation_mode="block",
    )


def _article(
    *,
    slug: str,
    title: str,
    description: str,
    body: str,
    tags: list[str],
) -> Article:
    return Article(
        slug=slug,
        title=title,
        description=description,
        body=body,
        tags=tags,
        author=Profile(username="real-ai-demo", bio="", image=None, following=False),
        favorited=False,
        favorites_count=0,
    )


async def test_real_llm_analyzes_article_draft() -> None:
    settings = _real_ai_settings()
    client = LLMClient(settings)
    service = ArticleAssistantService(client)
    try:
        analysis = await service.analyze_article(
            ArticleInCreate(
                title="城市散步与注意力恢复",
                description="记录通勤、街区散步和工作专注力之间的关系。",
                body=(
                    "我连续一个月在上班前进行二十分钟城市散步，发现早晨进入工作状态的速度更快。"
                    "街道噪声、绿化和步行节奏会影响情绪，也会影响后续处理复杂任务时的耐心。"
                    "这篇文章希望讨论城市生活中的微小恢复空间，以及如何把它变成稳定习惯。"
                ),
                tagList=["城市生活", "注意力"],
            ),
        )
    finally:
        await client.aclose()

    assert analysis.model == settings.llm_model
    assert analysis.summary
    assert analysis.suggestions
    assert 0 <= analysis.content_score <= 100
    assert analysis.reading_time_minutes >= 1


async def test_real_llm_moderates_risky_comment() -> None:
    settings = _real_ai_settings()
    client = LLMClient(settings)
    service = CommentModerationService(client, settings)
    article = _article(
        slug="city-focus",
        title="城市散步与注意力恢复",
        description="关于城市生活和专注力恢复的文章。",
        body="城市散步可以帮助作者恢复注意力。",
        tags=["城市生活", "注意力"],
    )
    user = User(username="commenter", email="commenter@example.com")
    try:
        moderation = await service.moderate_comment(
            article=article,
            user=user,
            body="限时优惠，点击陌生链接立刻领取高额返现，错过就没有了。",
        )
    finally:
        await client.aclose()

    assert moderation.model == settings.llm_model
    assert moderation.reason
    assert moderation.category in {
        "safe",
        "spam",
        "toxic",
        "harassment",
        "hate",
        "sexual",
        "violence",
        "self_harm",
        "irrelevant",
        "other",
    }
    assert moderation.severity in {"low", "medium", "high"}
    assert 0 <= moderation.confidence <= 1


async def test_real_llm_cross_reranker_scores_related_article() -> None:
    settings = _real_ai_settings()
    client = LLMClient(settings)
    reranker = CrossReranker(client)
    source = _article(
        slug="city-focus",
        title="城市散步与注意力恢复",
        description="记录城市生活中如何通过散步恢复专注力。",
        body="步行、街区环境和恢复性注意力有关。",
        tags=["城市生活", "注意力", "散步"],
    )
    candidate = _article(
        slug="morning-walk",
        title="早起散步后，我的工作日早晨变了什么",
        description="讨论散步、通勤和工作专注力之间的关系。",
        body="早起散步可以帮助进入更稳定的工作状态。",
        tags=["散步", "工作效率", "注意力"],
    )
    try:
        result = await reranker.score_pair(source, candidate)
    finally:
        await client.aclose()

    assert reranker.model_name == settings.llm_model
    assert 0 <= result.relevance_score <= 1
    assert result.reason
