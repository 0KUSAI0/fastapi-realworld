from typing import List, Optional

from asyncpg import Connection, Record

from app.db.errors import EntityDoesNotExist
from app.db.queries.queries import queries
from app.db.repositories.base import BaseRepository
from app.db.repositories.profiles import ProfilesRepository
from app.models.domain.articles import Article
from app.models.domain.comments import Comment
from app.models.domain.users import User
from app.models.schemas.admin import (
    ModerationDashboardInResponse,
    ModerationQueueItem,
    ModerationStats,
)
from app.models.schemas.comments import CommentModeration


class CommentsRepository(BaseRepository):
    def __init__(self, conn: Connection) -> None:
        super().__init__(conn)
        self._profiles_repo = ProfilesRepository(conn)

    async def get_comment_by_id(
        self,
        *,
        comment_id: int,
        article: Article,
        user: Optional[User] = None,
    ) -> Comment:
        comment_row = await self.connection.fetchrow(
            """
            SELECT c.id,
                   c.body,
                   c.content_status,
                   c.created_at,
                   c.updated_at,
                   (SELECT username FROM users WHERE id = c.author_id) as author_username,
                   (SELECT COUNT(*) FROM comment_likes cl WHERE cl.comment_id = c.id) AS likes_count,
                   CASE
                       WHEN $3::text IS NULL THEN FALSE
                       ELSE EXISTS (
                           SELECT 1
                           FROM comment_likes cl
                           INNER JOIN users u ON u.id = cl.user_id
                           WHERE cl.comment_id = c.id
                             AND u.username = $3
                       )
                   END AS liked
            FROM commentaries c
                     INNER JOIN articles a ON c.article_id = a.id AND (a.slug = $1)
            WHERE c.id = $2
            LIMIT 1
            """,
            article.slug,
            comment_id,
            user.username if user else None,
        )
        if comment_row:
            return await self._get_comment_from_db_record(
                comment_row=comment_row,
                author_username=comment_row["author_username"],
                requested_user=user,
            )

        raise EntityDoesNotExist(
            "comment with id {0} does not exist".format(comment_id),
        )

    async def get_comment_by_id_any_status(
        self,
        *,
        comment_id: int,
        article: Article,
        user: Optional[User] = None,
    ) -> Comment:
        comment_row = await self.connection.fetchrow(
            """
            SELECT c.id,
                   c.body,
                   c.content_status,
                   c.created_at,
                   c.updated_at,
                   (SELECT username FROM users WHERE id = c.author_id) as author_username
            FROM commentaries c
                     INNER JOIN articles a ON c.article_id = a.id AND (a.slug = $1)
            WHERE c.id = $2
            LIMIT 1
            """,
            article.slug,
            comment_id,
        )
        if comment_row:
            return await self._get_comment_from_db_record(
                comment_row=comment_row,
                author_username=comment_row["author_username"],
                requested_user=user,
            )
        raise EntityDoesNotExist(
            "comment with id {0} does not exist".format(comment_id),
        )

    async def get_comments_for_article(
        self,
        *,
        article: Article,
        user: Optional[User] = None,
    ) -> List[Comment]:
        comments_rows = await self.connection.fetch(
            """
            SELECT c.id,
                   c.body,
                   c.content_status,
                   c.created_at,
                   c.updated_at,
                   (SELECT username FROM users WHERE id = c.author_id) as author_username,
                   (SELECT COUNT(*) FROM comment_likes cl WHERE cl.comment_id = c.id) AS likes_count,
                   CASE
                       WHEN $2::text IS NULL THEN FALSE
                       ELSE EXISTS (
                           SELECT 1
                           FROM comment_likes cl
                           INNER JOIN users u ON u.id = cl.user_id
                           WHERE cl.comment_id = c.id
                             AND u.username = $2
                       )
                   END AS liked
            FROM commentaries c
                     INNER JOIN articles a ON c.article_id = a.id AND (a.slug = $1)
            WHERE c.content_status = 'visible'
            ORDER BY likes_count DESC, c.created_at DESC
            """,
            article.slug,
            user.username if user else None,
        )
        return [
            await self._get_comment_from_db_record(
                comment_row=comment_row,
                author_username=comment_row["author_username"],
                requested_user=user,
            )
            for comment_row in comments_rows
        ]

    async def create_comment_for_article(
        self,
        *,
        body: str,
        article: Article,
        user: User,
        content_status: str = "visible",
    ) -> Comment:
        comment_row = await queries.create_new_comment(
            self.connection,
            body=body,
            article_slug=article.slug,
            author_username=user.username,
            content_status=content_status,
        )
        return await self._get_comment_from_db_record(
            comment_row=comment_row,
            author_username=comment_row["author_username"],
            requested_user=user,
        )

    async def update_comment(
        self,
        *,
        comment: Comment,
        body: str,
    ) -> Comment:
        row = await self.connection.fetchrow(
            """
            UPDATE commentaries
            SET body = $2
            WHERE id = $1
            RETURNING id, body, content_status, created_at, updated_at
            """,
            comment.id_,
            body,
        )
        if not row:
            raise EntityDoesNotExist(
                "comment with id {0} does not exist".format(comment.id_),
            )
        return await self._get_comment_from_db_record(
            comment_row=row,
            author_username=comment.author.username,
            requested_user=None,
        )

    async def add_like_to_comment(self, *, comment: Comment, user: User) -> None:
        await self.connection.execute(
            """
            INSERT INTO comment_likes (user_id, comment_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            user.id_,
            comment.id_,
        )

    async def remove_like_from_comment(self, *, comment: Comment, user: User) -> None:
        result = await self.connection.execute(
            """
            DELETE FROM comment_likes
            WHERE user_id = $1
              AND comment_id = $2
            """,
            user.id_,
            comment.id_,
        )
        if result == "DELETE 0":
            raise EntityDoesNotExist(
                "comment like for user {0} and comment {1} does not exist".format(
                    user.username,
                    comment.id_,
                ),
            )

    async def create_moderation_log(
        self,
        *,
        body: str,
        article: Article,
        user: User,
        moderation: CommentModeration,
        comment: Optional[Comment] = None,
        review_status: Optional[str] = None,
    ) -> None:
        review_status = review_status or ("approved" if moderation.allowed else "pending")
        await self.connection.execute(
            """
            INSERT INTO comment_moderation_logs (
                article_id,
                author_id,
                comment_id,
                body,
                allowed,
                category,
                severity,
                reason,
                suggested_revision,
                confidence,
                model_name,
                raw_response,
                review_status
            )
            VALUES (
                $1,
                $2,
                $3,
                $4,
                $5,
                $6,
                $7,
                $8,
                $9,
                $10,
                $11,
                $12::json,
                $13
            )
            """,
            article.id_,
            user.id_,
            comment.id_ if comment else None,
            body,
            moderation.allowed,
            moderation.category,
            moderation.severity,
            moderation.reason,
            moderation.suggested_revision,
            moderation.confidence,
            moderation.model,
            moderation.json(by_alias=True),
            review_status,
        )

    async def get_moderation_dashboard(
        self,
        *,
        review_status: Optional[str] = "pending",
        q: Optional[str] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> ModerationDashboardInResponse:
        stats_row = await self.connection.fetchrow(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE c.content_status = 'hidden') AS blocked,
                COUNT(*) FILTER (WHERE review_status = 'pending') AS pending,
                COUNT(*) FILTER (WHERE severity = 'high') AS high_risk
            FROM comment_moderation_logs
            LEFT JOIN commentaries c ON c.id = comment_moderation_logs.comment_id
            """,
        )
        rows = await self.connection.fetch(
            """
            SELECT
                l.id,
                l.comment_id,
                l.body,
                l.allowed,
                l.category,
                l.severity,
                l.reason,
                l.suggested_revision,
                l.confidence,
                l.model_name,
                l.review_status,
                l.created_at,
                COALESCE(c.content_status, 'hidden') AS content_status,
                a.slug AS article_slug,
                a.title AS article_title,
                u.username AS author_username
            FROM comment_moderation_logs l
            INNER JOIN articles a ON a.id = l.article_id
            INNER JOIN users u ON u.id = l.author_id
            LEFT JOIN commentaries c ON c.id = l.comment_id
            WHERE (
                $1::text IS NULL
                OR l.review_status = $1
            )
              AND (
                $2::text IS NULL
                OR l.body ILIKE $2
                OR a.slug ILIKE $2
                OR a.title ILIKE $2
                OR u.username ILIKE $2
                OR l.category ILIKE $2
                OR l.reason ILIKE $2
              )
            ORDER BY l.created_at DESC
            LIMIT $3
            OFFSET $4
            """,
            None if review_status in (None, "", "all") else review_status,
            "%{0}%".format(q) if q else None,
            limit,
            offset,
        )
        count_row = await self.connection.fetchrow(
            """
            SELECT COUNT(*) AS items_count
            FROM comment_moderation_logs l
            INNER JOIN articles a ON a.id = l.article_id
            INNER JOIN users u ON u.id = l.author_id
            WHERE (
                $1::text IS NULL
                OR l.review_status = $1
            )
              AND (
                $2::text IS NULL
                OR l.body ILIKE $2
                OR a.slug ILIKE $2
                OR a.title ILIKE $2
                OR u.username ILIKE $2
                OR l.category ILIKE $2
                OR l.reason ILIKE $2
              )
            """,
            None if review_status in (None, "", "all") else review_status,
            "%{0}%".format(q) if q else None,
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
                    contentType="comment",
                    contentId=row["comment_id"],
                    articleSlug=row["article_slug"],
                    articleTitle=row["article_title"],
                    body=row["body"],
                    authorUsername=row["author_username"],
                    allowed=row["allowed"],
                    category=row["category"],
                    severity=row["severity"],
                    reason=row["reason"],
                    suggestedRevision=row["suggested_revision"],
                    confidence=row["confidence"],
                    model=row["model_name"],
                    contentStatus=row["content_status"],
                    reviewStatus=row["review_status"],
                    createdAt=row["created_at"],
                )
                for row in rows
            ],
            items_count=count_row["items_count"] if count_row else 0,
        )

    async def review_moderation_log(
        self,
        *,
        log_id: int,
        action: str,
        note: str = "",
    ) -> dict:
        row = await self.connection.fetchrow(
            """
            SELECT
                l.comment_id,
                l.article_id AS log_article_id,
                l.author_id AS log_author_id,
                l.body AS moderation_body,
                c.article_id,
                c.author_id,
                c.content_status
            FROM comment_moderation_logs l
            LEFT JOIN commentaries c ON c.id = l.comment_id
            WHERE l.id = $1
            """,
            log_id,
        )
        if not row:
            raise EntityDoesNotExist(
                "moderation log with id {0} does not exist".format(log_id),
            )
        review_status = "approved" if action == "approve" else "rejected"
        content_status = "visible" if action == "approve" else "hidden"
        await self.connection.execute(
            """
            WITH updated_log AS (
                UPDATE comment_moderation_logs
                SET review_status = $2,
                    review_note = $3
                WHERE id = $1
                RETURNING comment_id
            )
            UPDATE commentaries
            SET content_status = $4
            WHERE id = (SELECT comment_id FROM updated_log)
            """,
            log_id,
            review_status,
            note,
            content_status,
        )
        return {
            "content_type": "comment",
            "article_id": row["article_id"] or row["log_article_id"],
            "comment_id": row["comment_id"],
            "author_id": row["author_id"] or row["log_author_id"],
            "from_status": row["content_status"] or "",
            "to_status": content_status,
            "metadata": {"commentBody": row["moderation_body"]},
        }

    async def set_comment_content_status(
        self,
        *,
        comment_id: int,
        status: str,
    ) -> None:
        result = await self.connection.execute(
            """
            UPDATE commentaries
            SET content_status = $2
            WHERE id = $1
            """,
            comment_id,
            status,
        )
        if result == "UPDATE 0":
            raise EntityDoesNotExist(
                "comment with id {0} does not exist".format(comment_id),
            )

    async def delete_comment(self, *, comment: Comment) -> None:
        await queries.delete_comment_by_id(
            self.connection,
            comment_id=comment.id_,
            author_username=comment.author.username,
        )

    async def _get_comment_from_db_record(
        self,
        *,
        comment_row: Record,
        author_username: str,
        requested_user: Optional[User],
    ) -> Comment:
        return Comment(
            id_=comment_row["id"],
            body=comment_row["body"],
            content_status=comment_row["content_status"],
            liked=bool(comment_row["liked"]) if "liked" in comment_row.keys() else False,
            likes_count=(
                int(comment_row["likes_count"])
                if "likes_count" in comment_row.keys()
                else 0
            ),
            author=await self._profiles_repo.get_profile_by_username(
                username=author_username,
                requested_user=requested_user,
            ),
            created_at=comment_row["created_at"],
            updated_at=comment_row["updated_at"],
        )
