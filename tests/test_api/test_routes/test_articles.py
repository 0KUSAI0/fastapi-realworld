import pytest
from asyncpg.pool import Pool
from fastapi import FastAPI
from httpx import AsyncClient
from starlette import status

from app.core.config import get_app_settings
from app.core.settings.app import AppSettings
from app.core.settings.test import TestAppSettings as AppSettingsForTests
from app.api.dependencies.ai import (
    get_article_assistant_service,
    get_article_library_qa_service,
    get_article_polish_service,
    get_article_recommendation_service,
    get_article_suggestion_revision_service,
)
from app.db.errors import EntityDoesNotExist
from app.db.repositories.articles import ArticlesRepository
from app.db.repositories.profiles import ProfilesRepository
from app.db.repositories.users import UsersRepository
from app.models.domain.articles import Article
from app.models.domain.profiles import Profile
from app.models.domain.users import UserInDB
from app.models.schemas.articles import (
    ArticleAIAnalysis,
    ArticleAIAnalysisInResponse,
    ArticleForResponse,
    ArticleInResponse,
    ArticleLibraryQAInResponse,
    ArticleLibraryQAResult,
    ArticlePolishInResponse,
    ArticlePolishResult,
    ArticleSuggestionRevisionInResponse,
    ArticleSuggestionRevisionResult,
    ListOfArticlesInResponse,
    RecommendedArticleForResponse,
    RecommendedArticlesInResponse,
)
from app.services.ai.article_polish import ArticlePolishService
from app.services.ai.cross_reranker import CrossRankLLMResponse, CrossReranker

pytestmark = pytest.mark.asyncio


class FakeArticleAssistantService:
    def __init__(
        self,
        *,
        content_score: int = 87,
        risk_labels=None,
    ) -> None:
        self._content_score = content_score
        self._risk_labels = risk_labels or []

    async def analyze_article(self, article_create) -> ArticleAIAnalysis:
        return ArticleAIAnalysis(
            summary="LLM generated article summary.",
            recommendedTagList=["fastapi", "ai"],
            reading_time_minutes=2,
            content_score=self._content_score,
            riskLabels=self._risk_labels,
            suggestions=["Add a concrete API example."],
            model="fake-qwen",
        )


class FakeArticlePolishService:
    async def polish(self, *, text: str, instruction: str) -> ArticlePolishResult:
        return ArticlePolishResult(
            original=text,
            polished="改写后的文本。更简洁。",
            diff=[],
            critique="句子结构松散。",
            changes_summary=["拆分长句", "去除冗余"],
            improvement_score=0.82,
            iterations=1,
            model="fake-qwen",
        )


class FakeArticleSuggestionRevisionService:
    async def revise_for_suggestion(
        self,
        *,
        article,
        suggestion: str,
    ) -> ArticleSuggestionRevisionResult:
        return ArticleSuggestionRevisionResult(
            original=article.body,
            revised="改写后的正文。补充了具体示例。",
            diff=[],
            suggestion=suggestion,
            changedParagraphIndex=0,
            rationale="补充示例后内容更完整。",
            changesSummary=["补充具体示例"],
            confidence=0.88,
            model="fake-qwen",
        )


class FakeArticleRecommendationService:
    async def get_recommendations(
        self,
        *,
        article: Article,
        requested_user,
        limit: int,
    ):
        return [
            RecommendedArticleForResponse(
                article=ArticleForResponse.from_orm(article),
                similarityScore=0.76,
            )
        ][:limit]


class FakeArticleLibraryQAService:
    async def answer_question(
        self,
        *,
        question: str,
        requested_user,
        limit: int,
    ) -> ArticleLibraryQAResult:
        article = Article(
            slug="city-walks",
            title="City Walks and Focus",
            description="Walking helps restore attention.",
            body="A short walk can help people focus.",
            tags=["city", "focus"],
            author=Profile(username="demo", bio="", image=None, following=False),
            favorited=False,
            favorites_count=0,
        )
        return ArticleLibraryQAResult(
            question=question,
            answer="文章库里有关于城市散步和注意力恢复的内容。",
            sources=[
                RecommendedArticleForResponse(
                    article=ArticleForResponse.from_orm(article),
                    similarityScore=0.82,
                    reason="正文语义与搜索意图接近",
                )
            ],
            citations=["city-walks"],
            suggestedQueries=["还有哪些文章谈到通勤？"],
            model="fake-qwen",
        )


async def test_user_can_analyze_article_with_ai(
    app: FastAPI, authorized_client: AsyncClient
) -> None:
    app.dependency_overrides[get_article_assistant_service] = (
        lambda: FakeArticleAssistantService()
    )
    article_data = {
        "title": "FastAPI article quality review",
        "description": "AI assisted review for FastAPI article drafts.",
        "body": "FastAPI testing quality coverage " * 80,
        "tagList": ["AI", "FastAPI"],
    }
    try:
        response = await authorized_client.post(
            app.url_path_for("articles:analyze-article-with-ai"),
            json={"article": article_data},
        )
    finally:
        app.dependency_overrides.pop(get_article_assistant_service)

    assert response.status_code == status.HTTP_200_OK
    analysis = ArticleAIAnalysisInResponse(**response.json()).analysis
    assert analysis.summary == "LLM generated article summary."
    assert analysis.recommended_tags == ["fastapi", "ai"]
    assert analysis.content_score == 87
    assert analysis.model == "fake-qwen"


async def test_user_can_get_recommended_articles(
    app: FastAPI, authorized_client: AsyncClient, test_article: Article
) -> None:
    app.dependency_overrides[get_article_recommendation_service] = (
        lambda: FakeArticleRecommendationService()
    )
    try:
        response = await authorized_client.get(
            app.url_path_for(
                "articles:get-recommended-articles",
                slug=test_article.slug,
            ),
        )
    finally:
        app.dependency_overrides.pop(get_article_recommendation_service)

    assert response.status_code == status.HTTP_200_OK
    recommendations = RecommendedArticlesInResponse(**response.json())
    assert recommendations.articles_count == 1
    assert recommendations.articles[0].similarity_score == 0.76
    assert recommendations.articles[0].article.slug == test_article.slug


async def test_user_can_ask_article_library_ai(
    app: FastAPI, authorized_client: AsyncClient
) -> None:
    app.dependency_overrides[get_article_library_qa_service] = (
        lambda: FakeArticleLibraryQAService()
    )
    try:
        response = await authorized_client.post(
            app.url_path_for("articles:ask-article-library"),
            json={"question": "有没有关于城市散步的文章？", "limit": 3},
        )
    finally:
        app.dependency_overrides.pop(get_article_library_qa_service)

    assert response.status_code == status.HTTP_200_OK
    result = ArticleLibraryQAInResponse(**response.json()).result
    assert result.question == "有没有关于城市散步的文章？"
    assert result.answer == "文章库里有关于城市散步和注意力恢复的内容。"
    assert result.sources[0].article.slug == "city-walks"
    assert result.citations == ["city-walks"]
    assert result.suggested_queries == ["还有哪些文章谈到通勤？"]
    assert result.model == "fake-qwen"


async def test_user_can_get_recommendations_with_embedding_fallback(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    test_user: UserInDB,
    pool: Pool,
) -> None:
    settings = AppSettingsForTests(
        database_url="postgresql://postgres:postgres@localhost:15432/rwtest",
        embedding_model="sentence-transformers/not-cached",
        embedding_dimensions=384,
        embedding_allow_download=False,
        embedding_fallback_enabled=True,
    )
    app.dependency_overrides[get_app_settings] = lambda: settings

    from fastapi import Depends as _Depends

    from app.api.dependencies.database import get_repository as _get_repository
    from app.services.ai.article_recommendation import (
        ArticleRecommendationService as _ArticleRecommendationService,
    )
    from app.services.ai.embedding_client import EmbeddingClient as _EmbeddingClient

    def make_recommendation_service(
        articles_repo: ArticlesRepository = _Depends(
            _get_repository(ArticlesRepository),
        ),
    ) -> _ArticleRecommendationService:
        return _ArticleRecommendationService(
            embedding_client=_EmbeddingClient(settings),
            articles_repo=articles_repo,
            cross_reranker=None,
        )

    app.dependency_overrides[
        get_article_recommendation_service
    ] = make_recommendation_service
    async with pool.acquire() as connection:
        articles_repo = ArticlesRepository(connection)
        await articles_repo.create_article(
            slug="fastapi-ai-related",
            title="FastAPI AI recommendation",
            description="Embedding based article discovery",
            body="FastAPI semantic retrieval qwen embedding recommendation " * 20,
            author=test_user,
            tags=["fastapi", "ai"],
        )
        await articles_repo.create_article(
            slug="postgres-ops-related",
            title="PostgreSQL pgvector operations",
            description="Database setup notes",
            body="PostgreSQL pgvector docker migration index operations " * 20,
            author=test_user,
            tags=["postgres", "ops"],
        )

    try:
        response = await authorized_client.get(
            app.url_path_for(
                "articles:get-recommended-articles",
                slug=test_article.slug,
            ),
            params={"limit": 2},
        )
    finally:
        app.dependency_overrides.pop(get_app_settings)
        app.dependency_overrides.pop(get_article_recommendation_service)

    assert response.status_code == status.HTTP_200_OK
    recommendations = RecommendedArticlesInResponse(**response.json())
    assert recommendations.articles_count == 2
    assert {item.article.slug for item in recommendations.articles} == {
        "fastapi-ai-related",
        "postgres-ops-related",
    }

    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT model_name
            FROM article_embeddings
            ORDER BY article_id
            """,
        )

    assert len(rows) == 3
    assert {row["model_name"] for row in rows} == {"hashing-fallback-384"}


async def test_user_can_not_create_article_with_duplicated_slug(
    app: FastAPI, authorized_client: AsyncClient, test_article: Article
) -> None:
    article_data = {
        "title": "Test Slug",
        "body": "does not matter",
        "description": "¯\\_(ツ)_/¯",
    }
    response = await authorized_client.post(
        app.url_path_for("articles:create-article"), json={"article": article_data}
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


async def test_user_can_create_article(
    app: FastAPI, authorized_client: AsyncClient, test_user: UserInDB
) -> None:
    article_data = {
        "title": "Test Slug",
        "body": "does not matter",
        "description": "¯\\_(ツ)_/¯",
    }
    response = await authorized_client.post(
        app.url_path_for("articles:create-article"), json={"article": article_data}
    )
    article = ArticleInResponse(**response.json())
    assert article.article.title == article_data["title"]
    assert article.article.author.username == test_user.username


async def test_article_list_tolerates_visible_article_with_missing_author(
    app: FastAPI,
    authorized_client: AsyncClient,
    pool: Pool,
) -> None:
    async with pool.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO articles (slug, title, description, body, author_id, content_status)
            VALUES ('orphan-visible-article', 'Orphan Visible Article', 'desc', 'body', NULL, 'visible')
            """
        )

    response = await authorized_client.get(
        app.url_path_for("articles:list-articles"),
        params={"q": "Orphan Visible Article"},
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()["articles"][0]
    assert payload["slug"] == "orphan-visible-article"
    assert payload["author"]["username"] == "已删除用户"


async def test_author_can_update_hidden_article_and_resubmit_for_review(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_user: UserInDB,
    pool: Pool,
) -> None:
    async with pool.acquire() as connection:
        articles_repo = ArticlesRepository(connection)
        article = await articles_repo.create_article(
            slug="hidden-author-article",
            title="Hidden Author Article",
            description="Original description",
            body="Original body",
            author=test_user,
            tags=["hidden"],
            content_status="hidden",
        )

    response = await authorized_client.put(
        app.url_path_for("articles:update-article", slug=article.slug),
        json={
            "article": {
                "title": "Hidden Author Article Updated",
                "description": "Updated description",
                "body": "Updated body content",
                "tagList": ["updated", "review"],
                "submitForReview": True,
            }
        },
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()["article"]
    assert payload["title"] == "Hidden Author Article Updated"
    assert payload["contentStatus"] == "pending"


async def test_ai_review_can_hold_risky_article_for_review(
    app: FastAPI, authorized_client: AsyncClient
) -> None:
    app.dependency_overrides[get_article_assistant_service] = lambda: (
        FakeArticleAssistantService(content_score=20, risk_labels=["toxic"])
    )
    app.dependency_overrides[get_app_settings] = lambda: AppSettings(
        database_url="postgresql://postgres:postgres@localhost:15432/rwtest",
        secret_key="secret",
        ai_article_review_on_publish=True,
        ai_article_min_content_score=50,
    )
    try:
        response = await authorized_client.post(
            app.url_path_for("articles:create-article"),
            json={
                "article": {
                    "title": "Risky AI reviewed article",
                    "body": "unsafe content",
                    "description": "should be blocked",
                },
            },
        )
    finally:
        app.dependency_overrides.pop(get_article_assistant_service)
        app.dependency_overrides.pop(get_app_settings)

    assert response.status_code == status.HTTP_201_CREATED
    article = response.json()["article"]
    assert article["contentStatus"] == "pending"

    list_response = await authorized_client.get(
        app.url_path_for("articles:list-articles"),
        params={"q": "Risky AI reviewed article"},
    )

    assert list_response.status_code == status.HTTP_200_OK
    assert list_response.json()["articles"] == []

    moderation_response = await authorized_client.get(
        app.url_path_for("admin:get-article-moderation-dashboard"),
    )

    assert moderation_response.status_code == status.HTTP_200_OK
    dashboard = moderation_response.json()
    assert dashboard["stats"]["pending"] == 1
    assert dashboard["items"][0]["contentStatus"] == "pending"
    assert dashboard["items"][0]["contentScore"] == 20
    assert dashboard["items"][0]["riskLabels"] == ["toxic"]
    log_id = dashboard["items"][0]["id"]

    review_response = await authorized_client.post(
        app.url_path_for("admin:review-article-moderation-log", log_id=log_id),
        json={"action": "approve"},
    )

    assert review_response.status_code == status.HTTP_200_OK

    approved_list_response = await authorized_client.get(
        app.url_path_for("articles:list-articles"),
        params={"q": "Risky AI reviewed article"},
    )

    assert approved_list_response.status_code == status.HTTP_200_OK
    assert approved_list_response.json()["articles"][0]["slug"] == article["slug"]


async def test_not_existing_tags_will_be_created_without_duplication(
    app: FastAPI, authorized_client: AsyncClient, test_user: UserInDB
) -> None:
    article_data = {
        "title": "Test Slug",
        "body": "does not matter",
        "description": "¯\\_(ツ)_/¯",
        "tagList": ["tag1", "tag2", "tag3", "tag3"],
    }
    response = await authorized_client.post(
        app.url_path_for("articles:create-article"), json={"article": article_data}
    )
    article = ArticleInResponse(**response.json())
    assert set(article.article.tags) == {"tag1", "tag2", "tag3"}


@pytest.mark.parametrize(
    "api_method, route_name",
    (("GET", "articles:get-article"), ("PUT", "articles:update-article")),
)
async def test_user_can_not_retrieve_not_existing_article(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    api_method: str,
    route_name: str,
) -> None:
    response = await authorized_client.request(
        api_method, app.url_path_for(route_name, slug="wrong-slug")
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_user_can_retrieve_article_if_exists(
    app: FastAPI, authorized_client: AsyncClient, test_article: Article
) -> None:
    response = await authorized_client.get(
        app.url_path_for("articles:get-article", slug=test_article.slug)
    )
    article = ArticleInResponse(**response.json())
    assert article.article == test_article


@pytest.mark.parametrize(
    "update_field, update_value, extra_updates",
    (
        ("title", "New Title", {"slug": "new-title"}),
        ("description", "new description", {}),
        ("body", "new body", {}),
    ),
)
async def test_user_can_update_article(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    update_field: str,
    update_value: str,
    extra_updates: dict,
) -> None:
    response = await authorized_client.put(
        app.url_path_for("articles:update-article", slug=test_article.slug),
        json={"article": {update_field: update_value}},
    )

    assert response.status_code == status.HTTP_200_OK

    article = ArticleInResponse(**response.json()).article
    article_as_dict = article.dict()
    assert article_as_dict[update_field] == update_value

    for extra_field, extra_value in extra_updates.items():
        assert article_as_dict[extra_field] == extra_value

    exclude_fields = {update_field, *extra_updates.keys(), "updated_at"}
    assert article.dict(exclude=exclude_fields) == test_article.dict(
        exclude=exclude_fields
    )


@pytest.mark.parametrize(
    "api_method, route_name",
    (("PUT", "articles:update-article"), ("DELETE", "articles:delete-article")),
)
async def test_user_can_not_modify_article_that_is_not_authored_by_him(
    app: FastAPI,
    authorized_client: AsyncClient,
    pool: Pool,
    api_method: str,
    route_name: str,
) -> None:
    async with pool.acquire() as connection:
        users_repo = UsersRepository(connection)
        user = await users_repo.create_user(
            username="test_author", email="author@email.com", password="password"
        )
        articles_repo = ArticlesRepository(connection)
        await articles_repo.create_article(
            slug="test-slug",
            title="Test Slug",
            description="Slug for tests",
            body="Test " * 100,
            author=user,
            tags=["tests", "testing", "pytest"],
        )

    response = await authorized_client.request(
        api_method,
        app.url_path_for(route_name, slug="test-slug"),
        json={"article": {"title": "Updated Title"}},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


async def test_user_can_delete_his_article(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    pool: Pool,
) -> None:
    await authorized_client.delete(
        app.url_path_for("articles:delete-article", slug=test_article.slug)
    )

    async with pool.acquire() as connection:
        articles_repo = ArticlesRepository(connection)
        with pytest.raises(EntityDoesNotExist):
            await articles_repo.get_article_by_slug(slug=test_article.slug)


@pytest.mark.parametrize(
    "api_method, route_name, favorite_state",
    (
        ("POST", "articles:mark-article-favorite", True),
        ("DELETE", "articles:unmark-article-favorite", False),
    ),
)
async def test_user_can_change_favorite_state(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    test_user: UserInDB,
    pool: Pool,
    api_method: str,
    route_name: str,
    favorite_state: bool,
) -> None:
    if not favorite_state:
        async with pool.acquire() as connection:
            articles_repo = ArticlesRepository(connection)
            await articles_repo.add_article_into_favorites(
                article=test_article, user=test_user
            )

    await authorized_client.request(
        api_method, app.url_path_for(route_name, slug=test_article.slug)
    )

    response = await authorized_client.get(
        app.url_path_for("articles:get-article", slug=test_article.slug)
    )

    article = ArticleInResponse(**response.json())

    assert article.article.favorited == favorite_state
    assert article.article.favorites_count == int(favorite_state)


@pytest.mark.parametrize(
    "api_method, route_name, favorite_state",
    (
        ("POST", "articles:mark-article-favorite", True),
        ("DELETE", "articles:unmark-article-favorite", False),
    ),
)
async def test_user_can_not_change_article_state_twice(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    test_user: UserInDB,
    pool: Pool,
    api_method: str,
    route_name: str,
    favorite_state: bool,
) -> None:
    if favorite_state:
        async with pool.acquire() as connection:
            articles_repo = ArticlesRepository(connection)
            await articles_repo.add_article_into_favorites(
                article=test_article, user=test_user
            )

    response = await authorized_client.request(
        api_method, app.url_path_for(route_name, slug=test_article.slug)
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


async def test_empty_feed_if_user_has_not_followings(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    test_user: UserInDB,
    pool: Pool,
) -> None:
    async with pool.acquire() as connection:
        users_repo = UsersRepository(connection)
        articles_repo = ArticlesRepository(connection)

        for i in range(5):
            user = await users_repo.create_user(
                username=f"user-{i}", email=f"user-{i}@email.com", password="password"
            )
            for j in range(5):
                await articles_repo.create_article(
                    slug=f"slug-{i}-{j}",
                    title="tmp",
                    description="tmp",
                    body="tmp",
                    author=user,
                    tags=[f"tag-{i}-{j}"],
                )

    response = await authorized_client.get(
        app.url_path_for("articles:get-user-feed-articles")
    )

    articles = ListOfArticlesInResponse(**response.json())
    assert articles.articles == []


async def test_user_will_receive_only_following_articles(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    test_user: UserInDB,
    pool: Pool,
) -> None:
    following_author_username = "user-2"
    async with pool.acquire() as connection:
        users_repo = UsersRepository(connection)
        profiles_repo = ProfilesRepository(connection)
        articles_repo = ArticlesRepository(connection)

        for i in range(5):
            user = await users_repo.create_user(
                username=f"user-{i}", email=f"user-{i}@email.com", password="password"
            )
            if i == 2:
                await profiles_repo.add_user_into_followers(
                    target_user=user, requested_user=test_user
                )

            for j in range(5):
                await articles_repo.create_article(
                    slug=f"slug-{i}-{j}",
                    title="tmp",
                    description="tmp",
                    body="tmp",
                    author=user,
                    tags=[f"tag-{i}-{j}"],
                )

    response = await authorized_client.get(
        app.url_path_for("articles:get-user-feed-articles")
    )

    articles_from_response = ListOfArticlesInResponse(**response.json())
    assert len(articles_from_response.articles) == 5

    all_from_following = (
        article.author.username == following_author_username
        for article in articles_from_response.articles
    )
    assert all(all_from_following)


async def test_user_receiving_feed_with_limit_and_offset(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    test_user: UserInDB,
    pool: Pool,
) -> None:
    async with pool.acquire() as connection:
        users_repo = UsersRepository(connection)
        profiles_repo = ProfilesRepository(connection)
        articles_repo = ArticlesRepository(connection)

        for i in range(5):
            user = await users_repo.create_user(
                username=f"user-{i}", email=f"user-{i}@email.com", password="password"
            )
            if i == 2:
                await profiles_repo.add_user_into_followers(
                    target_user=user, requested_user=test_user
                )

            for j in range(5):
                await articles_repo.create_article(
                    slug=f"slug-{i}-{j}",
                    title="tmp",
                    description="tmp",
                    body="tmp",
                    author=user,
                    tags=[f"tag-{i}-{j}"],
                )

    full_response = await authorized_client.get(
        app.url_path_for("articles:get-user-feed-articles")
    )
    full_articles = ListOfArticlesInResponse(**full_response.json())

    response = await authorized_client.get(
        app.url_path_for("articles:get-user-feed-articles"),
        params={"limit": 2, "offset": 3},
    )

    articles_from_response = ListOfArticlesInResponse(**response.json())
    assert full_articles.articles[3:] == articles_from_response.articles


async def test_article_will_contain_only_attached_tags(
    app: FastAPI, authorized_client: AsyncClient, test_user: UserInDB, pool: Pool
) -> None:
    attached_tags = ["tag1", "tag3"]

    async with pool.acquire() as connection:
        articles_repo = ArticlesRepository(connection)

        await articles_repo.create_article(
            slug=f"test-slug",
            title="tmp",
            description="tmp",
            body="tmp",
            author=test_user,
            tags=attached_tags,
        )

        for i in range(5):
            await articles_repo.create_article(
                slug=f"slug-{i}",
                title="tmp",
                description="tmp",
                body="tmp",
                author=test_user,
                tags=[f"tag-{i}"],
            )

    response = await authorized_client.get(
        app.url_path_for("articles:get-article", slug="test-slug")
    )
    article = ArticleInResponse(**response.json())
    assert len(article.article.tags) == len(attached_tags)
    assert set(article.article.tags) == set(attached_tags)


@pytest.mark.parametrize(
    "tag, result", (("", 7), ("tag1", 1), ("tag2", 2), ("wrong", 0))
)
async def test_filtering_by_tags(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_user: UserInDB,
    pool: Pool,
    tag: str,
    result: int,
) -> None:
    async with pool.acquire() as connection:
        articles_repo = ArticlesRepository(connection)

        await articles_repo.create_article(
            slug=f"slug-1",
            title="tmp",
            description="tmp",
            body="tmp",
            author=test_user,
            tags=["tag1", "tag2"],
        )
        await articles_repo.create_article(
            slug=f"slug-2",
            title="tmp",
            description="tmp",
            body="tmp",
            author=test_user,
            tags=["tag2"],
        )

        for i in range(5, 10):
            await articles_repo.create_article(
                slug=f"slug-{i}",
                title="tmp",
                description="tmp",
                body="tmp",
                author=test_user,
                tags=[f"tag-{i}"],
            )

    response = await authorized_client.get(
        app.url_path_for("articles:list-articles"), params={"tag": tag}
    )
    articles = ListOfArticlesInResponse(**response.json())
    assert articles.articles_count == result


async def test_user_can_search_articles_by_keyword(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_user: UserInDB,
    pool: Pool,
) -> None:
    async with pool.acquire() as connection:
        articles_repo = ArticlesRepository(connection)

        await articles_repo.create_article(
            slug="semantic-fastapi",
            title="Semantic FastAPI search",
            description="A searchable backend article",
            body="This article explains qwen embeddings and fuzzy retrieval.",
            author=test_user,
            tags=["semantic-ai"],
        )
        await articles_repo.create_article(
            slug="unrelated",
            title="Deployment checklist",
            description="Operations notes",
            body="Docker and database setup.",
            author=test_user,
            tags=["ops"],
        )

    response = await authorized_client.get(
        app.url_path_for("articles:list-articles"),
        params={"q": "semantic"},
    )
    articles = ListOfArticlesInResponse(**response.json())

    assert articles.articles_count == 1
    assert articles.articles[0].slug == "semantic-fastapi"


@pytest.mark.parametrize(
    "author, result", (("", 8), ("author1", 1), ("author2", 2), ("wrong", 0))
)
async def test_filtering_by_authors(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_user: UserInDB,
    pool: Pool,
    author: str,
    result: int,
) -> None:
    async with pool.acquire() as connection:
        users_repo = UsersRepository(connection)
        articles_repo = ArticlesRepository(connection)

        author1 = await users_repo.create_user(
            username="author1", email="author1@email.com", password="password"
        )
        author2 = await users_repo.create_user(
            username="author2", email="author2@email.com", password="password"
        )

        await articles_repo.create_article(
            slug=f"slug-1", title="tmp", description="tmp", body="tmp", author=author1
        )
        await articles_repo.create_article(
            slug=f"slug-2-1", title="tmp", description="tmp", body="tmp", author=author2
        )
        await articles_repo.create_article(
            slug=f"slug-2-2", title="tmp", description="tmp", body="tmp", author=author2
        )

        for i in range(5, 10):
            await articles_repo.create_article(
                slug=f"slug-{i}",
                title="tmp",
                description="tmp",
                body="tmp",
                author=test_user,
            )

    response = await authorized_client.get(
        app.url_path_for("articles:list-articles"), params={"author": author}
    )
    articles = ListOfArticlesInResponse(**response.json())
    assert articles.articles_count == result


@pytest.mark.parametrize(
    "favorited, result", (("", 7), ("fan1", 1), ("fan2", 2), ("wrong", 0))
)
async def test_filtering_by_favorited(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_user: UserInDB,
    pool: Pool,
    favorited: str,
    result: int,
) -> None:
    async with pool.acquire() as connection:
        users_repo = UsersRepository(connection)
        articles_repo = ArticlesRepository(connection)

        fan1 = await users_repo.create_user(
            username="fan1", email="fan1@email.com", password="password"
        )
        fan2 = await users_repo.create_user(
            username="fan2", email="fan2@email.com", password="password"
        )

        article1 = await articles_repo.create_article(
            slug=f"slug-1", title="tmp", description="tmp", body="tmp", author=test_user
        )
        article2 = await articles_repo.create_article(
            slug=f"slug-2", title="tmp", description="tmp", body="tmp", author=test_user
        )

        await articles_repo.add_article_into_favorites(article=article1, user=fan1)
        await articles_repo.add_article_into_favorites(article=article1, user=fan2)
        await articles_repo.add_article_into_favorites(article=article2, user=fan2)

        for i in range(5, 10):
            await articles_repo.create_article(
                slug=f"slug-{i}",
                title="tmp",
                description="tmp",
                body="tmp",
                author=test_user,
            )

    response = await authorized_client.get(
        app.url_path_for("articles:list-articles"), params={"favorited": favorited}
    )
    articles = ListOfArticlesInResponse(**response.json())
    assert articles.articles_count == result


async def test_filtering_with_limit_and_offset(
    app: FastAPI, authorized_client: AsyncClient, test_user: UserInDB, pool: Pool
) -> None:
    async with pool.acquire() as connection:
        articles_repo = ArticlesRepository(connection)

        for i in range(5, 10):
            await articles_repo.create_article(
                slug=f"slug-{i}",
                title="tmp",
                description="tmp",
                body="tmp",
                author=test_user,
            )

    full_response = await authorized_client.get(
        app.url_path_for("articles:list-articles")
    )
    full_articles = ListOfArticlesInResponse(**full_response.json())

    response = await authorized_client.get(
        app.url_path_for("articles:list-articles"), params={"limit": 2, "offset": 3}
    )

    articles_from_response = ListOfArticlesInResponse(**response.json())
    assert full_articles.articles[3:] == articles_from_response.articles


async def test_user_can_polish_article_section(
    app: FastAPI, authorized_client: AsyncClient
) -> None:
    app.dependency_overrides[get_article_polish_service] = lambda: FakeArticlePolishService()
    try:
        response = await authorized_client.post(
            app.url_path_for("articles:polish-article-section"),
            json={
                "body": "FastAPI 是一个基于 Python 的高性能 Web 框架，它提供了异步请求处理能力，学习起来也非常简单方便。",
                "instruction": "使语言更简洁",
            },
        )
    finally:
        app.dependency_overrides.pop(get_article_polish_service)

    assert response.status_code == status.HTTP_200_OK
    result = ArticlePolishInResponse(**response.json()).result
    assert result.polished == "改写后的文本。更简洁。"
    assert result.improvement_score == pytest.approx(0.82)
    assert result.iterations == 1
    assert result.model == "fake-qwen"
    assert result.changes_summary == ["拆分长句", "去除冗余"]


async def test_polish_returns_original_and_diff(
    app: FastAPI, authorized_client: AsyncClient
) -> None:
    original_text = "这是原始文本。"
    app.dependency_overrides[get_article_polish_service] = lambda: FakeArticlePolishService()
    try:
        response = await authorized_client.post(
            app.url_path_for("articles:polish-article-section"),
            json={"body": original_text, "instruction": "改善表达"},
        )
    finally:
        app.dependency_overrides.pop(get_article_polish_service)

    assert response.status_code == status.HTTP_200_OK
    result = ArticlePolishInResponse(**response.json()).result
    assert result.original == original_text
    assert isinstance(result.diff, list)


async def test_polish_requires_authentication(
    app: FastAPI, client: AsyncClient
) -> None:
    response = await client.post(
        app.url_path_for("articles:polish-article-section"),
        json={"body": "some text", "instruction": "polish it"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


async def test_user_can_revise_article_for_selected_suggestion(
    app: FastAPI, authorized_client: AsyncClient
) -> None:
    app.dependency_overrides[get_article_suggestion_revision_service] = (
        lambda: FakeArticleSuggestionRevisionService()
    )
    try:
        response = await authorized_client.post(
            app.url_path_for("articles:revise-article-suggestion"),
            json={
                "article": {
                    "title": "FastAPI article quality review",
                    "description": "AI assisted review for FastAPI drafts.",
                    "body": "原始正文。",
                    "tagList": ["fastapi"],
                },
                "suggestion": "补充具体示例。",
            },
        )
    finally:
        app.dependency_overrides.pop(get_article_suggestion_revision_service)

    assert response.status_code == status.HTTP_200_OK
    result = ArticleSuggestionRevisionInResponse(**response.json()).result
    assert result.original == "原始正文。"
    assert result.revised == "改写后的正文。补充了具体示例。"
    assert result.suggestion == "补充具体示例。"
    assert result.changed_paragraph_index == 0
    assert result.confidence == pytest.approx(0.88)
    assert result.model == "fake-qwen"


async def test_revise_article_suggestion_requires_authentication(
    app: FastAPI, client: AsyncClient
) -> None:
    response = await client.post(
        app.url_path_for("articles:revise-article-suggestion"),
        json={
            "article": {
                "title": "Draft",
                "description": "Draft description",
                "body": "Draft body",
                "tagList": [],
            },
            "suggestion": "补充细节。",
        },
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


async def test_recommendations_use_cross_reranker_scores(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    test_user: UserInDB,
    pool: Pool,
) -> None:
    """Cross-reranker LLM score should replace pure embedding similarity."""
    from fastapi import Depends as _Depends

    from app.api.dependencies.database import get_repository as _get_repository
    from app.services.ai.article_recommendation import (
        ArticleRecommendationService as _ARS,
    )
    from app.services.ai.embedding_client import FakeEmbeddingClient

    class HighScoreCrossReranker:
        model_name = "high-score"

        async def score_pairs(self, source, candidates):
            return [
                CrossRankLLMResponse(relevance_score=0.95, reason="深度相关")
                for _ in candidates
            ]

    async with pool.acquire() as connection:
        articles_repo = ArticlesRepository(connection)
        await articles_repo.create_article(
            slug="cross-reranked-target",
            title="Cross Reranked Target",
            description="Pgvector cross reranker test",
            body="cross reranker embedding fastapi pgvector recommendation " * 20,
            author=test_user,
            tags=["ai", "fastapi"],
        )

    def make_cross_rerank_service(
        articles_repo: ArticlesRepository = _Depends(
            _get_repository(ArticlesRepository),
        ),
    ) -> _ARS:
        return _ARS(
            embedding_client=FakeEmbeddingClient(),
            articles_repo=articles_repo,
            cross_reranker=HighScoreCrossReranker(),
        )

    app.dependency_overrides[get_article_recommendation_service] = make_cross_rerank_service
    app.dependency_overrides[get_app_settings] = lambda: AppSettingsForTests(
        database_url="postgresql://postgres:postgres@localhost:15432/rwtest",
        embedding_model="sentence-transformers/not-cached",
        embedding_dimensions=384,
        embedding_allow_download=False,
        embedding_fallback_enabled=True,
    )
    try:
        response = await authorized_client.get(
            app.url_path_for(
                "articles:get-recommended-articles",
                slug=test_article.slug,
            ),
            params={"limit": 1},
        )
    finally:
        app.dependency_overrides.pop(get_article_recommendation_service)
        app.dependency_overrides.pop(get_app_settings)

    assert response.status_code == status.HTTP_200_OK
    recommendations = RecommendedArticlesInResponse(**response.json())
    assert recommendations.articles_count == 1
    rec = recommendations.articles[0]
    assert rec.reason == "深度相关"
    assert rec.article.slug == "cross-reranked-target"


async def test_cross_reranker_reason_is_persisted_and_reused_from_cache(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    test_user: UserInDB,
    pool: Pool,
) -> None:
    """Second request for the same article pair should read from DB cache,
    not call the LLM again."""
    from fastapi import Depends as _Depends

    from app.api.dependencies.database import get_repository as _get_repository
    from app.services.ai.article_recommendation import (
        ArticleRecommendationService as _ARS,
    )
    from app.services.ai.embedding_client import FakeEmbeddingClient

    score_call_count = 0

    class CountingCrossReranker:
        model_name = "counting-cross"

        async def score_pairs(self, source, candidates):
            nonlocal score_call_count
            score_call_count += len(candidates)
            return [
                CrossRankLLMResponse(relevance_score=0.88, reason="缓存测试理由")
                for _ in candidates
            ]

    async with pool.acquire() as connection:
        articles_repo = ArticlesRepository(connection)
        await articles_repo.create_article(
            slug="cache-persist-target",
            title="Cache Persist Target",
            description="Testing reason cache persistence between requests",
            body="cache recommendation reason persistence test pgvector " * 20,
            author=test_user,
            tags=["cache", "ai"],
        )

    reranker = CountingCrossReranker()

    def make_cache_service(
        articles_repo: ArticlesRepository = _Depends(
            _get_repository(ArticlesRepository),
        ),
    ) -> _ARS:
        return _ARS(
            embedding_client=FakeEmbeddingClient(),
            articles_repo=articles_repo,
            cross_reranker=reranker,
        )

    app.dependency_overrides[get_article_recommendation_service] = make_cache_service
    app.dependency_overrides[get_app_settings] = lambda: AppSettingsForTests(
        database_url="postgresql://postgres:postgres@localhost:15432/rwtest",
        embedding_model="sentence-transformers/not-cached",
        embedding_dimensions=384,
        embedding_allow_download=False,
        embedding_fallback_enabled=True,
    )
    try:
        first_response = await authorized_client.get(
            app.url_path_for(
                "articles:get-recommended-articles",
                slug=test_article.slug,
            ),
            params={"limit": 1},
        )
        calls_after_first = score_call_count

        second_response = await authorized_client.get(
            app.url_path_for(
                "articles:get-recommended-articles",
                slug=test_article.slug,
            ),
            params={"limit": 1},
        )
    finally:
        app.dependency_overrides.pop(get_article_recommendation_service)
        app.dependency_overrides.pop(get_app_settings)

    assert first_response.status_code == status.HTTP_200_OK
    assert second_response.status_code == status.HTTP_200_OK
    assert calls_after_first >= 1
    assert score_call_count == calls_after_first
