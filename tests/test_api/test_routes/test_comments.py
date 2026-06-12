import pytest
from asyncpg.pool import Pool
from fastapi import FastAPI
from httpx import AsyncClient
from starlette import status

from app.api.dependencies.ai import get_comment_moderation_service
from app.db.repositories.comments import CommentsRepository
from app.db.repositories.users import UsersRepository
from app.models.domain.articles import Article
from app.models.domain.users import UserInDB
from app.models.schemas.comments import (
    CommentInResponse,
    CommentModeration,
    CommentModerationInResponse,
    ListOfCommentsInResponse,
)

pytestmark = pytest.mark.asyncio


class FakeCommentModerationService:
    def __init__(
        self,
        *,
        enabled_for_comment_creation: bool = False,
        should_block_rejected_comments: bool = False,
    ) -> None:
        self.enabled_for_comment_creation = enabled_for_comment_creation
        self.should_block_rejected_comments = should_block_rejected_comments

    async def moderate_comment(self, *, article, user, body) -> CommentModeration:
        return CommentModeration(
            allowed=False,
            category="spam",
            severity="high",
            reason="包含推广内容。",
            suggestedRevision="删除推广语后重新提交。",
            confidence=0.93,
            model="fake-qwen",
        )


async def test_user_can_add_comment_for_article(
    app: FastAPI, authorized_client: AsyncClient, test_article: Article
) -> None:
    created_comment_response = await authorized_client.post(
        app.url_path_for("comments:create-comment-for-article", slug=test_article.slug),
        json={"comment": {"body": "comment"}},
    )

    created_comment = CommentInResponse(**created_comment_response.json())

    comments_for_article_response = await authorized_client.get(
        app.url_path_for("comments:get-comments-for-article", slug=test_article.slug)
    )

    comments = ListOfCommentsInResponse(**comments_for_article_response.json())

    assert created_comment.comment == comments.comments[0]


async def test_user_can_like_and_unlike_comment(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
) -> None:
    created_response = await authorized_client.post(
        app.url_path_for("comments:create-comment-for-article", slug=test_article.slug),
        json={"comment": {"body": "likeable comment"}},
    )
    comment_id = created_response.json()["comment"]["id"]

    like_response = await authorized_client.post(
        app.url_path_for(
            "comments:like-comment",
            slug=test_article.slug,
            comment_id=comment_id,
        ),
    )

    assert like_response.status_code == status.HTTP_200_OK
    assert like_response.json()["comment"]["liked"] is True
    assert like_response.json()["comment"]["likesCount"] == 1

    unlike_response = await authorized_client.delete(
        app.url_path_for(
            "comments:unlike-comment",
            slug=test_article.slug,
            comment_id=comment_id,
        ),
    )

    assert unlike_response.status_code == status.HTTP_200_OK
    assert unlike_response.json()["comment"]["liked"] is False
    assert unlike_response.json()["comment"]["likesCount"] == 0


async def test_user_can_moderate_comment_with_ai(
    app: FastAPI, authorized_client: AsyncClient, test_article: Article
) -> None:
    app.dependency_overrides[get_comment_moderation_service] = (
        lambda: FakeCommentModerationService()
    )
    try:
        response = await authorized_client.post(
            app.url_path_for(
                "comments:moderate-comment-for-article",
                slug=test_article.slug,
            ),
            json={"comment": {"body": "buy now"}},
        )
    finally:
        app.dependency_overrides.pop(get_comment_moderation_service)

    assert response.status_code == status.HTTP_200_OK
    moderation = CommentModerationInResponse(**response.json()).moderation
    assert moderation.allowed is False
    assert moderation.category == "spam"
    assert moderation.model == "fake-qwen"


async def test_ai_moderation_can_hold_risky_comment_for_review(
    app: FastAPI, authorized_client: AsyncClient, test_article: Article
) -> None:
    app.dependency_overrides[get_comment_moderation_service] = lambda: (
        FakeCommentModerationService(
            enabled_for_comment_creation=True,
            should_block_rejected_comments=True,
        )
    )
    try:
        response = await authorized_client.post(
            app.url_path_for(
                "comments:create-comment-for-article",
                slug=test_article.slug,
            ),
            json={"comment": {"body": "buy now"}},
        )
    finally:
        app.dependency_overrides.pop(get_comment_moderation_service)

    assert response.status_code == status.HTTP_201_CREATED
    comment = response.json()["comment"]
    assert comment["contentStatus"] == "pending"

    comments_response = await authorized_client.get(
        app.url_path_for("comments:get-comments-for-article", slug=test_article.slug),
    )

    assert comments_response.status_code == status.HTTP_200_OK
    assert comments_response.json()["comments"] == []


async def test_user_can_review_moderation_queue(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
) -> None:
    app.dependency_overrides[get_comment_moderation_service] = lambda: (
        FakeCommentModerationService(
            enabled_for_comment_creation=True,
            should_block_rejected_comments=True,
        )
    )
    try:
        await authorized_client.post(
            app.url_path_for(
                "comments:create-comment-for-article",
                slug=test_article.slug,
            ),
            json={"comment": {"body": "buy now"}},
        )
    finally:
        app.dependency_overrides.pop(get_comment_moderation_service)

    dashboard_response = await authorized_client.get(
        app.url_path_for("admin:get-moderation-dashboard"),
    )

    assert dashboard_response.status_code == status.HTTP_200_OK
    dashboard = dashboard_response.json()
    assert dashboard["stats"]["blocked"] == 0
    assert dashboard["stats"]["pending"] == 1
    log_id = dashboard["items"][0]["id"]
    assert dashboard["items"][0]["contentStatus"] == "pending"

    review_response = await authorized_client.post(
        app.url_path_for("admin:review-moderation-log", log_id=log_id),
        json={"action": "approve"},
    )

    assert review_response.status_code == status.HTTP_200_OK
    reviewed_dashboard = review_response.json()
    assert reviewed_dashboard["stats"]["blocked"] == 0
    assert reviewed_dashboard["stats"]["pending"] == 0
    assert reviewed_dashboard["items"] == []

    comments_response = await authorized_client.get(
        app.url_path_for("comments:get-comments-for-article", slug=test_article.slug),
    )

    assert comments_response.status_code == status.HTTP_200_OK
    assert len(comments_response.json()["comments"]) == 1


async def test_comments_are_sorted_by_likes_count(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    pool: Pool,
) -> None:
    first_response = await authorized_client.post(
        app.url_path_for("comments:create-comment-for-article", slug=test_article.slug),
        json={"comment": {"body": "first comment"}},
    )
    second_response = await authorized_client.post(
        app.url_path_for("comments:create-comment-for-article", slug=test_article.slug),
        json={"comment": {"body": "second comment"}},
    )

    first_id = first_response.json()["comment"]["id"]
    second_id = second_response.json()["comment"]["id"]

    async with pool.acquire() as connection:
        users_repo = UsersRepository(connection)
        await users_repo.create_user(
            username="comment_fan",
            email="comment_fan@email.com",
            password="password",
        )
        fan = await users_repo.get_user_by_username(username="comment_fan")
        comments_repo = CommentsRepository(connection)
        first_comment = await comments_repo.get_comment_by_id(
            comment_id=first_id,
            article=test_article,
        )
        await comments_repo.add_like_to_comment(comment=first_comment, user=fan)

    response = await authorized_client.get(
        app.url_path_for("comments:get-comments-for-article", slug=test_article.slug),
    )

    assert response.status_code == status.HTTP_200_OK
    comments = response.json()["comments"]
    assert comments[0]["id"] == first_id
    assert comments[1]["id"] == second_id


async def test_user_can_delete_own_comment(
    app: FastAPI, authorized_client: AsyncClient, test_article: Article
) -> None:
    created_comment_response = await authorized_client.post(
        app.url_path_for("comments:create-comment-for-article", slug=test_article.slug),
        json={"comment": {"body": "comment"}},
    )

    created_comment = CommentInResponse(**created_comment_response.json())

    await authorized_client.delete(
        app.url_path_for(
            "comments:delete-comment-from-article",
            slug=test_article.slug,
            comment_id=str(created_comment.comment.id_),
        )
    )

    comments_for_article_response = await authorized_client.get(
        app.url_path_for("comments:get-comments-for-article", slug=test_article.slug)
    )

    comments = ListOfCommentsInResponse(**comments_for_article_response.json())

    assert len(comments.comments) == 0


async def test_author_can_update_hidden_comment_and_resubmit_for_review(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    pool: Pool,
    test_user: UserInDB,
) -> None:
    async with pool.acquire() as connection:
        comments_repo = CommentsRepository(connection)
        comment = await comments_repo.create_comment_for_article(
            body="original hidden comment",
            article=test_article,
            user=test_user,
            content_status="hidden",
        )

    response = await authorized_client.put(
        app.url_path_for(
            "comments:update-comment-for-article",
            slug=test_article.slug,
            comment_id=comment.id_,
        ),
        json={
            "comment": {
                "body": "updated hidden comment",
                "submitForReview": True,
            }
        },
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()["comment"]
    assert payload["body"] == "updated hidden comment"
    assert payload["contentStatus"] == "pending"


async def test_user_can_not_delete_not_authored_comment(
    app: FastAPI, authorized_client: AsyncClient, test_article: Article, pool: Pool
) -> None:
    async with pool.acquire() as connection:
        users_repo = UsersRepository(connection)
        user = await users_repo.create_user(
            username="test_author", email="author@email.com", password="password"
        )
        comments_repo = CommentsRepository(connection)
        comment = await comments_repo.create_comment_for_article(
            body="tmp", article=test_article, user=user
        )

    forbidden_response = await authorized_client.delete(
        app.url_path_for(
            "comments:delete-comment-from-article",
            slug=test_article.slug,
            comment_id=str(comment.id_),
        )
    )

    assert forbidden_response.status_code == status.HTTP_403_FORBIDDEN


async def test_user_will_receive_error_for_not_existing_comment(
    app: FastAPI, authorized_client: AsyncClient, test_article: Article
) -> None:
    not_found_response = await authorized_client.delete(
        app.url_path_for(
            "comments:delete-comment-from-article",
            slug=test_article.slug,
            comment_id="1",
        )
    )

    assert not_found_response.status_code == status.HTTP_404_NOT_FOUND
