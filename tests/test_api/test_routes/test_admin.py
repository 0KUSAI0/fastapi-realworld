import pytest
from asyncpg.pool import Pool
from fastapi import FastAPI
from httpx import AsyncClient
from starlette import status

from app.core.config import get_app_settings
from app.core.settings.test import TestAppSettings as AppSettingsForTests
from app.db.repositories.articles import ArticlesRepository
from app.db.repositories.comments import CommentsRepository
from app.db.repositories.users import UsersRepository
from app.models.domain.articles import Article
from app.models.domain.users import UserInDB
from app.services import jwt

pytestmark = pytest.mark.asyncio


async def test_admin_can_get_overview(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
) -> None:
    response = await authorized_client.get(app.url_path_for("admin:get-overview"))

    assert response.status_code == status.HTTP_200_OK
    stats = response.json()["stats"]
    assert stats["usersCount"] == 1
    assert stats["articlesCount"] == 1
    assert stats["commentsCount"] == 0


async def test_admin_can_manage_articles(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_user: UserInDB,
    pool: Pool,
) -> None:
    async with pool.acquire() as connection:
        articles_repo = ArticlesRepository(connection)
        await articles_repo.create_article(
            slug="admin-fastapi-search",
            title="FastAPI admin search",
            description="Article for the admin backend.",
            body="FastAPI article management.",
            author=test_user,
            tags=["fastapi", "admin"],
        )

    list_response = await authorized_client.get(
        app.url_path_for("admin:list-articles"),
        params={"q": "fastapi"},
    )

    assert list_response.status_code == status.HTTP_200_OK
    articles = list_response.json()["articles"]
    assert [article["slug"] for article in articles] == ["admin-fastapi-search"]

    hide_response = await authorized_client.delete(
        app.url_path_for("admin:delete-article", slug="admin-fastapi-search"),
    )

    assert hide_response.status_code == status.HTTP_204_NO_CONTENT

    empty_response = await authorized_client.get(
        app.url_path_for("admin:list-articles"),
        params={"q": "admin-fastapi-search"},
    )

    assert empty_response.status_code == status.HTTP_200_OK
    assert empty_response.json()["articles"] == []

    hidden_response = await authorized_client.get(
        app.url_path_for("admin:list-articles"),
        params={"q": "admin-fastapi-search", "status": "hidden"},
    )

    assert hidden_response.status_code == status.HTTP_200_OK
    assert hidden_response.json()["articles"][0]["slug"] == "admin-fastapi-search"

    restore_response = await authorized_client.put(
        app.url_path_for("admin:update-article-status", slug="admin-fastapi-search"),
        json={"status": "visible"},
    )

    assert restore_response.status_code == status.HTTP_204_NO_CONTENT


async def test_admin_can_get_full_article_details_when_article_is_hidden(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_user: UserInDB,
    pool: Pool,
) -> None:
    body = "Full admin article body. " * 24
    async with pool.acquire() as connection:
        articles_repo = ArticlesRepository(connection)
        await articles_repo.create_article(
            slug="admin-full-article",
            title="Admin Full Article",
            description="Article detail coverage.",
            body=body,
            author=test_user,
            tags=["detail", "admin"],
        )

    hide_response = await authorized_client.delete(
        app.url_path_for("admin:delete-article", slug="admin-full-article"),
    )

    assert hide_response.status_code == status.HTTP_204_NO_CONTENT

    detail_response = await authorized_client.get(
        app.url_path_for("admin:get-article", slug="admin-full-article"),
    )

    assert detail_response.status_code == status.HTTP_200_OK
    article = detail_response.json()["article"]
    assert article["slug"] == "admin-full-article"
    assert article["body"] == body
    assert article["contentStatus"] == "hidden"


async def test_admin_can_manage_comments(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
) -> None:
    created_response = await authorized_client.post(
        app.url_path_for(
            "comments:create-comment-for-article",
            slug=test_article.slug,
        ),
        json={"comment": {"body": "FastAPI admin comment"}},
    )
    comment_id = created_response.json()["comment"]["id"]

    list_response = await authorized_client.get(
        app.url_path_for("admin:list-comments"),
        params={"q": "admin comment"},
    )

    assert list_response.status_code == status.HTTP_200_OK
    comments = list_response.json()["comments"]
    assert len(comments) == 1
    assert comments[0]["id"] == comment_id
    assert comments[0]["articleSlug"] == test_article.slug

    hide_response = await authorized_client.delete(
        app.url_path_for("admin:delete-comment", comment_id=comment_id),
    )

    assert hide_response.status_code == status.HTTP_204_NO_CONTENT

    empty_response = await authorized_client.get(
        app.url_path_for("admin:list-comments"),
        params={"q": "admin comment"},
    )

    assert empty_response.status_code == status.HTTP_200_OK
    assert empty_response.json()["comments"] == []

    hidden_response = await authorized_client.get(
        app.url_path_for("admin:list-comments"),
        params={"q": "admin comment", "status": "hidden"},
    )

    assert hidden_response.status_code == status.HTTP_200_OK
    assert hidden_response.json()["comments"][0]["id"] == comment_id

    restore_response = await authorized_client.put(
        app.url_path_for("admin:update-comment-status", comment_id=comment_id),
        json={"status": "visible"},
    )

    assert restore_response.status_code == status.HTTP_204_NO_CONTENT


async def test_admin_can_view_comment_threads_and_article_comments(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
) -> None:
    created_response = await authorized_client.post(
        app.url_path_for(
            "comments:create-comment-for-article",
            slug=test_article.slug,
        ),
        json={"comment": {"body": "threaded admin comment"}},
    )
    comment_id = created_response.json()["comment"]["id"]

    threads_response = await authorized_client.get(
        app.url_path_for("admin:list-comment-threads"),
        params={"status": "all"},
    )

    assert threads_response.status_code == status.HTTP_200_OK
    threads = threads_response.json()["threads"]
    assert threads[0]["articleSlug"] == test_article.slug
    assert threads[0]["commentsCount"] >= 1

    article_comments_response = await authorized_client.get(
        app.url_path_for("admin:list-article-comments", slug=test_article.slug),
        params={"status": "all"},
    )

    assert article_comments_response.status_code == status.HTTP_200_OK
    comments = article_comments_response.json()["comments"]
    assert any(comment["id"] == comment_id for comment in comments)


async def test_admin_can_handle_article_report_with_audit_and_notification(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
) -> None:
    report_response = await authorized_client.post(
        app.url_path_for("articles:report-article", slug=test_article.slug),
        json={"report": {"reason": "unsafe", "detail": "This article needs review."}},
    )

    assert report_response.status_code == status.HTTP_200_OK
    assert report_response.json()["status"] == "pending"

    reports_response = await authorized_client.get(
        app.url_path_for("admin:list-content-reports"),
        params={"status": "pending"},
    )

    assert reports_response.status_code == status.HTTP_200_OK
    reports = reports_response.json()["reports"]
    assert len(reports) == 1
    assert reports[0]["contentType"] == "article"
    assert reports[0]["articleSlug"] == test_article.slug

    review_response = await authorized_client.post(
        app.url_path_for("admin:review-content-report", report_id=reports[0]["id"]),
        json={"action": "hide", "note": "Confirmed by admin."},
    )

    assert review_response.status_code == status.HTTP_200_OK

    hidden_article_response = await authorized_client.get(
        app.url_path_for("articles:get-article", slug=test_article.slug),
    )

    assert hidden_article_response.status_code == status.HTTP_404_NOT_FOUND

    audit_response = await authorized_client.get(
        app.url_path_for("admin:list-content-audit-logs"),
        params={"q": "Confirmed by admin."},
    )

    assert audit_response.status_code == status.HTTP_200_OK
    audit_log = audit_response.json()["logs"][0]
    assert audit_log["action"] == "report_hide"
    assert audit_log["fromStatus"] == "visible"
    assert audit_log["toStatus"] == "hidden"

    notifications_response = await authorized_client.get(
        app.url_path_for("users:list-notifications"),
    )

    assert notifications_response.status_code == status.HTTP_200_OK
    notification = notifications_response.json()["notifications"][0]
    assert notification["notificationType"] == "report_hide"
    assert notification["isRead"] is False

    read_response = await authorized_client.put(
        app.url_path_for(
            "users:mark-notification-read",
            notification_id=notification["id"],
        ),
    )

    assert read_response.status_code == status.HTTP_204_NO_CONTENT

    export_response = await authorized_client.get(
        app.url_path_for("admin:export-content-audit-logs"),
    )

    assert export_response.status_code == status.HTTP_200_OK
    assert "audit-logs.csv" in export_response.headers["content-disposition"]
    assert "id,content_type,target,action,from_status,to_status,actor,created_at,note" in export_response.text


async def test_admin_audit_log_keeps_comment_body_for_rejected_report(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
) -> None:
    comment_body = "Comment body that should remain visible in audit history."
    created_response = await authorized_client.post(
        app.url_path_for(
            "comments:create-comment-for-article",
            slug=test_article.slug,
        ),
        json={"comment": {"body": comment_body}},
    )
    comment_id = created_response.json()["comment"]["id"]

    report_response = await authorized_client.post(
        app.url_path_for(
            "comments:report-comment",
            slug=test_article.slug,
            comment_id=comment_id,
        ),
        json={"report": {"reason": "spam", "detail": "Please review this comment."}},
    )

    assert report_response.status_code == status.HTTP_200_OK

    reports_response = await authorized_client.get(
        app.url_path_for("admin:list-content-reports"),
        params={"status": "pending", "type": "comment"},
    )

    assert reports_response.status_code == status.HTTP_200_OK
    report = reports_response.json()["reports"][0]
    assert report["commentBody"] == comment_body

    review_response = await authorized_client.post(
        app.url_path_for("admin:review-content-report", report_id=report["id"]),
        json={"action": "ignore", "note": "Report rejected after review."},
    )

    assert review_response.status_code == status.HTTP_200_OK

    audit_response = await authorized_client.get(
        app.url_path_for("admin:list-content-audit-logs"),
        params={"type": "comment", "q": "Report rejected after review."},
    )

    assert audit_response.status_code == status.HTTP_200_OK
    audit_log = audit_response.json()["logs"][0]
    assert audit_log["action"] == "report_ignore"
    assert audit_log["commentId"] == comment_id
    assert audit_log["commentBody"] == comment_body


async def test_non_admin_can_not_access_admin_api(
    app: FastAPI,
    client: AsyncClient,
    test_user: UserInDB,
    pool: Pool,
    authorization_prefix: str,
) -> None:
    app.dependency_overrides[get_app_settings] = lambda: AppSettingsForTests(
        database_url="postgresql://postgres:postgres@localhost:15432/rwtest",
        admin_usernames=["admin-only"],
    )
    token = jwt.create_access_token_for_user(test_user, "test_secret")
    client.headers = {
        "Authorization": f"{authorization_prefix} {token}",
        **client.headers,
    }
    try:
        response = await client.get(app.url_path_for("admin:get-overview"))
    finally:
        app.dependency_overrides.pop(get_app_settings)

    assert response.status_code == status.HTTP_403_FORBIDDEN


async def test_user_can_get_current_user_content(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
) -> None:
    await authorized_client.post(
        app.url_path_for(
            "comments:create-comment-for-article",
            slug=test_article.slug,
        ),
        json={"comment": {"body": "my user content comment"}},
    )

    response = await authorized_client.get(
        app.url_path_for("users:get-current-user-content"),
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["articlesCount"] >= 1
    assert payload["commentsCount"] >= 1


async def test_user_content_supports_status_filter_and_type_switch(
    app: FastAPI,
    authorized_client: AsyncClient,
    test_article: Article,
    pool: Pool,
) -> None:
    await authorized_client.post(
        app.url_path_for(
            "comments:create-comment-for-article",
            slug=test_article.slug,
        ),
        json={"comment": {"body": "visible comment"}},
    )
    async with pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE commentaries
            SET content_status = 'hidden'
            WHERE body = 'visible comment'
            """
        )

    response = await authorized_client.get(
        app.url_path_for("users:get-current-user-content"),
        params={"type": "comments", "status": "hidden"},
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["contentType"] == "comments"
    assert payload["commentsCount"] >= 1
    assert payload["comments"][0]["contentStatus"] == "hidden"
