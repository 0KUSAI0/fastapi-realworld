import json
from typing import List, Optional

from asyncpg import Connection

from app.db.errors import EntityDoesNotExist
from app.db.repositories.articles import ArticlesRepository
from app.db.repositories.base import BaseRepository
from app.models.domain.articles import Article
from app.models.domain.users import User
from app.models.schemas.admin import (
    AdminArticlesInResponse,
    AdminCommentItem,
    AdminCommentsInResponse,
    AdminCommentThreadItem,
    AdminCommentThreadsInResponse,
    AdminOverviewInResponse,
    AdminOverviewStats,
    ModerationDashboardInResponse,
    ModerationQueueItem,
    ModerationStats,
)
from app.models.schemas.articles import ArticleForResponse


class AdminRepository(BaseRepository):
    def __init__(self, conn: Connection) -> None:
        super().__init__(conn)
        self._articles_repo = ArticlesRepository(conn)

    async def get_overview(self) -> AdminOverviewInResponse:
        row = await self.connection.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM users) AS users_count,
                (SELECT COUNT(*) FROM articles) AS articles_count,
                (
                    SELECT COUNT(*) FROM articles
                    WHERE content_status = 'visible'
                ) AS articles_visible,
                (
                    SELECT COUNT(*) FROM articles
                    WHERE content_status = 'pending'
                ) AS articles_pending,
                (
                    SELECT COUNT(*) FROM articles
                    WHERE content_status = 'hidden'
                ) AS articles_hidden,
                (SELECT COUNT(*) FROM commentaries) AS comments_count,
                (
                    SELECT COUNT(*) FROM commentaries
                    WHERE content_status = 'visible'
                ) AS comments_visible,
                (
                    SELECT COUNT(*) FROM commentaries
                    WHERE content_status = 'pending'
                ) AS comments_pending,
                (
                    SELECT COUNT(*) FROM commentaries
                    WHERE content_status = 'hidden'
                ) AS comments_hidden,
                (SELECT COUNT(*) FROM comment_moderation_logs) AS moderation_total,
                (
                    SELECT COUNT(*)
                    FROM comment_moderation_logs
                    WHERE review_status = 'pending'
                ) AS moderation_pending,
                (
                    SELECT COUNT(*)
                    FROM comment_moderation_logs
                    INNER JOIN commentaries c ON c.id = comment_moderation_logs.comment_id
                    WHERE c.content_status = 'hidden'
                ) AS moderation_blocked,
                (SELECT COUNT(*) FROM article_moderation_logs) AS article_moderation_total,
                (
                    SELECT COUNT(*)
                    FROM article_moderation_logs
                    WHERE review_status = 'pending'
                ) AS article_moderation_pending,
                (
                    SELECT COUNT(*)
                    FROM article_moderation_logs
                    INNER JOIN articles a ON a.id = article_moderation_logs.article_id
                    WHERE a.content_status = 'hidden'
                ) AS article_moderation_blocked,
                (
                    SELECT COUNT(*)
                    FROM comment_moderation_logs
                    WHERE severity = 'high'
                ) + (
                    SELECT COUNT(*)
                    FROM article_moderation_logs
                    WHERE json_array_length(risk_labels) > 0
                ) AS high_risk
            """,
        )
        return AdminOverviewInResponse(
            stats=AdminOverviewStats(
                users_count=row["users_count"] if row else 0,
                articles_count=row["articles_count"] if row else 0,
                articles_visible=row["articles_visible"] if row else 0,
                articles_pending=row["articles_pending"] if row else 0,
                articles_hidden=row["articles_hidden"] if row else 0,
                comments_count=row["comments_count"] if row else 0,
                comments_visible=row["comments_visible"] if row else 0,
                comments_pending=row["comments_pending"] if row else 0,
                comments_hidden=row["comments_hidden"] if row else 0,
                moderation_total=row["moderation_total"] if row else 0,
                moderation_pending=row["moderation_pending"] if row else 0,
                moderation_blocked=row["moderation_blocked"] if row else 0,
                article_moderation_total=row["article_moderation_total"] if row else 0,
                article_moderation_pending=(
                    row["article_moderation_pending"] if row else 0
                ),
                article_moderation_blocked=(
                    row["article_moderation_blocked"] if row else 0
                ),
                highRisk=row["high_risk"] if row else 0,
            ),
        )

    async def list_articles(
        self,
        *,
        requested_user: Optional[User],
        q: Optional[str] = None,
        content_status: Optional[str] = "visible",
        limit: int = 30,
        offset: int = 0,
    ) -> AdminArticlesInResponse:
        rows = await self.connection.fetch(
            """
            SELECT
                a.id,
                a.slug,
                a.title,
                a.description,
                a.body,
                a.content_status,
                a.created_at,
                a.updated_at,
                u.username AS author_username
            FROM articles a
            INNER JOIN users u ON u.id = a.author_id
            WHERE (
                $1::text IS NULL
                OR a.content_status = $1
            )
              AND (
                $2::text IS NULL
                OR a.slug ILIKE $2
                OR a.title ILIKE $2
                OR a.description ILIKE $2
                OR a.body ILIKE $2
                OR u.username ILIKE $2
                OR EXISTS (
                    SELECT 1
                    FROM articles_to_tags att
                    WHERE att.article_id = a.id
                      AND att.tag ILIKE $2
                )
              )
            ORDER BY a.created_at DESC
            LIMIT $3
            OFFSET $4
            """,
            None if content_status in (None, "", "all") else content_status,
            "%{0}%".format(q) if q else None,
            limit,
            offset,
        )
        count_row = await self.connection.fetchrow(
            """
            SELECT COUNT(*) AS articles_count
            FROM articles a
            INNER JOIN users u ON u.id = a.author_id
            WHERE (
                $1::text IS NULL
                OR a.content_status = $1
            )
              AND (
                $2::text IS NULL
                OR a.slug ILIKE $2
                OR a.title ILIKE $2
                OR a.description ILIKE $2
                OR a.body ILIKE $2
                OR u.username ILIKE $2
                OR EXISTS (
                    SELECT 1
                    FROM articles_to_tags att
                    WHERE att.article_id = a.id
                      AND att.tag ILIKE $2
                )
              )
            """,
            None if content_status in (None, "", "all") else content_status,
            "%{0}%".format(q) if q else None,
        )
        return AdminArticlesInResponse(
            articles=[
                ArticleForResponse.from_orm(
                    await self._articles_repo._get_article_from_db_record(
                        article_row=row,
                        slug=row["slug"],
                        author_username=row["author_username"],
                        requested_user=requested_user,
                    ),
                )
                for row in rows
            ],
            articles_count=count_row["articles_count"] if count_row else 0,
        )

    async def get_article(
        self,
        *,
        slug: str,
        requested_user: Optional[User],
    ) -> Article:
        row = await self.connection.fetchrow(
            """
            SELECT
                a.id,
                a.slug,
                a.title,
                a.description,
                a.body,
                a.content_status,
                a.created_at,
                a.updated_at,
                u.username AS author_username
            FROM articles a
            INNER JOIN users u ON u.id = a.author_id
            WHERE a.slug = $1
            LIMIT 1
            """,
            slug,
        )
        if not row:
            raise EntityDoesNotExist(
                "article with slug {0} does not exist".format(slug),
            )
        return await self._articles_repo._get_article_from_db_record(
            article_row=row,
            slug=row["slug"],
            author_username=row["author_username"],
            requested_user=requested_user,
        )

    async def delete_article(self, *, slug: str) -> None:
        await self.set_article_status(slug=slug, content_status="hidden")

    async def set_article_status(self, *, slug: str, content_status: str) -> dict:
        row = await self.connection.fetchrow(
            """
            SELECT id, author_id, content_status
            FROM articles
            WHERE slug = $1
            """,
            slug,
        )
        if not row:
            raise EntityDoesNotExist(
                "article with slug {0} does not exist".format(slug),
            )
        await self.connection.execute(
            """
            UPDATE articles
            SET content_status = $2
            WHERE slug = $1
            """,
            slug,
            content_status,
        )
        return {
            "content_type": "article",
            "article_id": row["id"],
            "comment_id": None,
            "author_id": row["author_id"],
            "from_status": row["content_status"],
            "to_status": content_status,
        }

    async def list_comments(
        self,
        *,
        q: Optional[str] = None,
        content_status: Optional[str] = "visible",
        limit: int = 30,
        offset: int = 0,
    ) -> AdminCommentsInResponse:
        rows = await self.connection.fetch(
            """
            SELECT
                c.id,
                c.body,
                c.content_status,
                c.created_at,
                c.updated_at,
                a.slug AS article_slug,
                a.title AS article_title,
                u.username AS author_username
            FROM commentaries c
            INNER JOIN articles a ON a.id = c.article_id
            INNER JOIN users u ON u.id = c.author_id
            WHERE (
                $1::text IS NULL
                OR c.content_status = $1
            )
              AND (
                $2::text IS NULL
                OR c.body ILIKE $2
                OR a.slug ILIKE $2
                OR a.title ILIKE $2
                OR u.username ILIKE $2
            )
            ORDER BY c.created_at DESC
            LIMIT $3
            OFFSET $4
            """,
            None if content_status in (None, "", "all") else content_status,
            "%{0}%".format(q) if q else None,
            limit,
            offset,
        )
        count_row = await self.connection.fetchrow(
            """
            SELECT COUNT(*) AS comments_count
            FROM commentaries c
            INNER JOIN articles a ON a.id = c.article_id
            INNER JOIN users u ON u.id = c.author_id
            WHERE (
                $1::text IS NULL
                OR c.content_status = $1
            )
              AND (
                $2::text IS NULL
                OR c.body ILIKE $2
                OR a.slug ILIKE $2
                OR a.title ILIKE $2
                OR u.username ILIKE $2
            )
            """,
            None if content_status in (None, "", "all") else content_status,
            "%{0}%".format(q) if q else None,
        )
        return AdminCommentsInResponse(
            comments=[
                AdminCommentItem(
                    id=row["id"],
                    body=row["body"],
                    content_status=row["content_status"],
                    article_slug=row["article_slug"],
                    article_title=row["article_title"],
                    author_username=row["author_username"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ],
            comments_count=count_row["comments_count"] if count_row else 0,
        )

    async def list_comment_threads(
        self,
        *,
        q: Optional[str] = None,
        content_status: Optional[str] = "visible",
        limit: int = 30,
        offset: int = 0,
    ) -> AdminCommentThreadsInResponse:
        status_filter = None if content_status in (None, "", "all") else content_status
        search_filter = "%{0}%".format(q) if q else None
        rows = await self.connection.fetch(
            """
            SELECT
                a.slug AS article_slug,
                a.title AS article_title,
                a.content_status AS article_content_status,
                COUNT(*) AS comments_count,
                COUNT(*) FILTER (WHERE c.content_status = 'visible') AS visible_count,
                COUNT(*) FILTER (WHERE c.content_status = 'hidden') AS hidden_count,
                COUNT(*) FILTER (WHERE c.content_status = 'pending') AS pending_count,
                (
                    SELECT c2.body
                    FROM commentaries c2
                    WHERE c2.article_id = a.id
                      AND (
                        $1::text IS NULL
                        OR c2.content_status = $1
                      )
                    ORDER BY c2.created_at DESC
                    LIMIT 1
                ) AS latest_comment_body,
                MAX(c.created_at) AS latest_comment_at
            FROM commentaries c
            INNER JOIN articles a ON a.id = c.article_id
            INNER JOIN users u ON u.id = c.author_id
            WHERE (
                $1::text IS NULL
                OR c.content_status = $1
            )
              AND (
                $2::text IS NULL
                OR c.body ILIKE $2
                OR a.slug ILIKE $2
                OR a.title ILIKE $2
                OR u.username ILIKE $2
              )
            GROUP BY a.id, a.slug, a.title, a.content_status
            ORDER BY latest_comment_at DESC
            LIMIT $3
            OFFSET $4
            """,
            status_filter,
            search_filter,
            limit,
            offset,
        )
        count_row = await self.connection.fetchrow(
            """
            SELECT COUNT(*) AS threads_count
            FROM (
                SELECT a.id
                FROM commentaries c
                INNER JOIN articles a ON a.id = c.article_id
                INNER JOIN users u ON u.id = c.author_id
                WHERE (
                    $1::text IS NULL
                    OR c.content_status = $1
                )
                  AND (
                    $2::text IS NULL
                    OR c.body ILIKE $2
                    OR a.slug ILIKE $2
                    OR a.title ILIKE $2
                    OR u.username ILIKE $2
                  )
                GROUP BY a.id
            ) grouped_threads
            """,
            status_filter,
            search_filter,
        )
        return AdminCommentThreadsInResponse(
            threads=[
                AdminCommentThreadItem(
                    article_slug=row["article_slug"],
                    article_title=row["article_title"],
                    articleContentStatus=row["article_content_status"],
                    commentsCount=row["comments_count"],
                    visibleCount=row["visible_count"],
                    hiddenCount=row["hidden_count"],
                    pendingCount=row["pending_count"],
                    latestCommentBody=row["latest_comment_body"] or "",
                    latestCommentAt=row["latest_comment_at"],
                )
                for row in rows
            ],
            threadsCount=count_row["threads_count"] if count_row else 0,
        )

    async def list_comments_for_article(
        self,
        *,
        slug: str,
        q: Optional[str] = None,
        content_status: Optional[str] = "all",
        limit: int = 50,
        offset: int = 0,
    ) -> AdminCommentsInResponse:
        status_filter = None if content_status in (None, "", "all") else content_status
        search_filter = "%{0}%".format(q) if q else None
        rows = await self.connection.fetch(
            """
            SELECT
                c.id,
                c.body,
                c.content_status,
                c.created_at,
                c.updated_at,
                a.slug AS article_slug,
                a.title AS article_title,
                u.username AS author_username
            FROM commentaries c
            INNER JOIN articles a ON a.id = c.article_id
            INNER JOIN users u ON u.id = c.author_id
            WHERE a.slug = $1
              AND (
                $2::text IS NULL
                OR c.content_status = $2
              )
              AND (
                $3::text IS NULL
                OR c.body ILIKE $3
                OR u.username ILIKE $3
              )
            ORDER BY c.created_at DESC
            LIMIT $4
            OFFSET $5
            """,
            slug,
            status_filter,
            search_filter,
            limit,
            offset,
        )
        count_row = await self.connection.fetchrow(
            """
            SELECT COUNT(*) AS comments_count
            FROM commentaries c
            INNER JOIN articles a ON a.id = c.article_id
            INNER JOIN users u ON u.id = c.author_id
            WHERE a.slug = $1
              AND (
                $2::text IS NULL
                OR c.content_status = $2
              )
              AND (
                $3::text IS NULL
                OR c.body ILIKE $3
                OR u.username ILIKE $3
              )
            """,
            slug,
            status_filter,
            search_filter,
        )
        return AdminCommentsInResponse(
            comments=[
                AdminCommentItem(
                    id=row["id"],
                    body=row["body"],
                    content_status=row["content_status"],
                    article_slug=row["article_slug"],
                    article_title=row["article_title"],
                    author_username=row["author_username"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ],
            comments_count=count_row["comments_count"] if count_row else 0,
        )

    async def delete_comment(self, *, comment_id: int) -> None:
        await self.set_comment_status(
            comment_id=comment_id,
            content_status="hidden",
        )

    async def set_comment_status(self, *, comment_id: int, content_status: str) -> dict:
        row = await self.connection.fetchrow(
            """
            SELECT id, article_id, author_id, content_status, body
            FROM commentaries
            WHERE id = $1
            """,
            comment_id,
        )
        if not row:
            raise EntityDoesNotExist(
                "comment with id {0} does not exist".format(comment_id),
            )
        await self.connection.execute(
            """
            UPDATE commentaries
            SET content_status = $2
            WHERE id = $1
            """,
            comment_id,
            content_status,
        )
        return {
            "content_type": "comment",
            "article_id": row["article_id"],
            "comment_id": row["id"],
            "author_id": row["author_id"],
            "from_status": row["content_status"],
            "to_status": content_status,
            "metadata": {"commentBody": row["body"]},
        }

    async def get_article_moderation_dashboard(
        self,
        *,
        review_status: Optional[str] = "pending",
        q: Optional[str] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> ModerationDashboardInResponse:
        status_filter = None if review_status in (None, "", "all") else review_status
        search_filter = "%{0}%".format(q) if q else None
        stats_row = await self.connection.fetchrow(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE a.content_status = 'hidden') AS blocked,
                COUNT(*) FILTER (WHERE l.review_status = 'pending') AS pending,
                COUNT(*) FILTER (WHERE json_array_length(l.risk_labels) > 0) AS high_risk
            FROM article_moderation_logs l
            INNER JOIN articles a ON a.id = l.article_id
            """,
        )
        rows = await self.connection.fetch(
            """
            SELECT
                l.id,
                l.allowed,
                l.content_score,
                l.risk_labels,
                l.summary,
                l.suggestions,
                l.model_name,
                l.review_status,
                l.created_at,
                a.slug,
                a.title,
                a.description,
                a.body,
                a.content_status,
                u.username AS author_username
            FROM article_moderation_logs l
            INNER JOIN articles a ON a.id = l.article_id
            INNER JOIN users u ON u.id = l.author_id
            WHERE (
                $1::text IS NULL
                OR l.review_status = $1
            )
              AND (
                $2::text IS NULL
                OR a.slug ILIKE $2
                OR a.title ILIKE $2
                OR a.description ILIKE $2
                OR a.body ILIKE $2
                OR u.username ILIKE $2
                OR l.summary ILIKE $2
              )
            ORDER BY l.created_at DESC
            LIMIT $3
            OFFSET $4
            """,
            status_filter,
            search_filter,
            limit,
            offset,
        )
        count_row = await self.connection.fetchrow(
            """
            SELECT COUNT(*) AS items_count
            FROM article_moderation_logs l
            INNER JOIN articles a ON a.id = l.article_id
            INNER JOIN users u ON u.id = l.author_id
            WHERE (
                $1::text IS NULL
                OR l.review_status = $1
            )
              AND (
                $2::text IS NULL
                OR a.slug ILIKE $2
                OR a.title ILIKE $2
                OR a.description ILIKE $2
                OR a.body ILIKE $2
                OR u.username ILIKE $2
                OR l.summary ILIKE $2
              )
            """,
            status_filter,
            search_filter,
        )
        return ModerationDashboardInResponse(
            stats=ModerationStats(
                total=stats_row["total"] if stats_row else 0,
                blocked=stats_row["blocked"] if stats_row else 0,
                pending=stats_row["pending"] if stats_row else 0,
                highRisk=stats_row["high_risk"] if stats_row else 0,
            ),
            items=[
                ModerationQueueItem(
                    id=row["id"],
                    contentType="article",
                    articleSlug=row["slug"],
                    title=row["title"],
                    body=row["body"],
                    authorUsername=row["author_username"],
                    allowed=row["allowed"],
                    category="article",
                    severity=(
                        "high" if self._json_list(row["risk_labels"]) else "medium"
                    ),
                    reason=row["summary"],
                    contentScore=row["content_score"],
                    riskLabels=self._json_list(row["risk_labels"]),
                    suggestions=self._json_list(row["suggestions"]),
                    confidence=1.0,
                    model=row["model_name"],
                    contentStatus=row["content_status"],
                    reviewStatus=row["review_status"],
                    createdAt=row["created_at"],
                )
                for row in rows
            ],
            items_count=count_row["items_count"] if count_row else 0,
        )

    async def review_article_moderation_log(
        self,
        *,
        log_id: int,
        action: str,
        note: str = "",
    ) -> dict:
        row = await self.connection.fetchrow(
            """
            SELECT
                l.article_id,
                a.author_id,
                a.content_status
            FROM article_moderation_logs l
            INNER JOIN articles a ON a.id = l.article_id
            WHERE l.id = $1
            """,
            log_id,
        )
        if not row:
            raise EntityDoesNotExist(
                "article moderation log with id {0} does not exist".format(log_id),
            )
        review_status = "approved" if action == "approve" else "rejected"
        content_status = "visible" if action == "approve" else "hidden"
        await self.connection.execute(
            """
            WITH updated_log AS (
                UPDATE article_moderation_logs
                SET review_status = $2,
                    review_note = $3
                WHERE id = $1
                RETURNING article_id
            )
            UPDATE articles
            SET content_status = $4
            WHERE id = (SELECT article_id FROM updated_log)
            """,
            log_id,
            review_status,
            note,
            content_status,
        )
        return {
            "content_type": "article",
            "article_id": row["article_id"],
            "comment_id": None,
            "author_id": row["author_id"],
            "from_status": row["content_status"],
            "to_status": content_status,
        }

    def _json_list(self, value: object) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, str):
            try:
                loaded = json.loads(value)
            except json.JSONDecodeError:
                return [value] if value else []
            if isinstance(loaded, list):
                return [str(item) for item in loaded]
        return []
