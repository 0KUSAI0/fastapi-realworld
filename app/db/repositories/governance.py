import json
from typing import Dict, List, Optional

from asyncpg import Connection

from app.db.errors import EntityDoesNotExist
from app.db.repositories.base import BaseRepository
from app.models.domain.articles import Article
from app.models.domain.comments import Comment
from app.models.domain.users import User
from app.models.schemas.governance import (
    ContentAuditLogItem,
    ContentAuditLogsInResponse,
    ContentReportInResponse,
    ContentReportItem,
    ContentReportsInResponse,
    UserContentCommentItem,
    UserContentInResponse,
    UserContentArticleItem,
    UserContentOverview,
    UserNotificationItem,
    UserNotificationsInResponse,
)


class GovernanceRepository(BaseRepository):
    def __init__(self, conn: Connection) -> None:
        super().__init__(conn)

    async def create_article_report(
        self,
        *,
        article: Article,
        reporter: User,
        reason: str,
        detail: str = "",
    ) -> ContentReportInResponse:
        row = await self.connection.fetchrow(
            """
            INSERT INTO content_reports (
                content_type,
                reporter_id,
                article_id,
                reason,
                detail
            )
            VALUES ('article', $1, $2, $3, $4)
            RETURNING id, content_type, reason, detail, status, created_at
            """,
            reporter.id_,
            article.id_,
            reason,
            detail,
        )
        return ContentReportInResponse(**dict(row))

    async def create_comment_report(
        self,
        *,
        article: Article,
        comment: Comment,
        reporter: User,
        reason: str,
        detail: str = "",
    ) -> ContentReportInResponse:
        row = await self.connection.fetchrow(
            """
            INSERT INTO content_reports (
                content_type,
                reporter_id,
                article_id,
                comment_id,
                reason,
                detail
            )
            VALUES ('comment', $1, $2, $3, $4, $5)
            RETURNING id, content_type, reason, detail, status, created_at
            """,
            reporter.id_,
            article.id_,
            comment.id_,
            reason,
            detail,
        )
        return ContentReportInResponse(**dict(row))

    async def list_reports(
        self,
        *,
        status: Optional[str] = "pending",
        content_type: Optional[str] = "all",
        q: Optional[str] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> ContentReportsInResponse:
        status_filter = None if status in (None, "", "all") else status
        type_filter = None if content_type in (None, "", "all") else content_type
        search_filter = "%{0}%".format(q) if q else None
        rows = await self.connection.fetch(
            """
            SELECT
                r.id,
                r.content_type,
                r.reason,
                r.detail,
                r.status,
                r.resolution_note,
                r.created_at,
                r.resolved_at,
                reporter.username AS reporter_username,
                COALESCE(article_author.username, comment_author.username, '') AS author_username,
                COALESCE(a.slug, report_article.slug, '') AS article_slug,
                COALESCE(a.title, report_article.title, '') AS article_title,
                c.id AS comment_id,
                COALESCE(c.body, '') AS comment_body,
                COALESCE(c.content_status, a.content_status, '') AS content_status,
                COALESCE(resolver.username, '') AS resolved_by_username
            FROM content_reports r
            INNER JOIN users reporter ON reporter.id = r.reporter_id
            LEFT JOIN articles a ON a.id = r.article_id AND r.content_type = 'article'
            LEFT JOIN users article_author ON article_author.id = a.author_id
            LEFT JOIN commentaries c ON c.id = r.comment_id
            LEFT JOIN users comment_author ON comment_author.id = c.author_id
            LEFT JOIN articles report_article ON report_article.id = c.article_id
            LEFT JOIN users resolver ON resolver.id = r.resolved_by_id
            WHERE (
                $1::text IS NULL
                OR r.status = $1
            )
              AND (
                $2::text IS NULL
                OR r.content_type = $2
            )
              AND (
                $3::text IS NULL
                OR r.reason ILIKE $3
                OR r.detail ILIKE $3
                OR reporter.username ILIKE $3
                OR a.slug ILIKE $3
                OR a.title ILIKE $3
                OR c.body ILIKE $3
                OR report_article.slug ILIKE $3
                OR report_article.title ILIKE $3
              )
            ORDER BY r.created_at DESC
            LIMIT $4
            OFFSET $5
            """,
            status_filter,
            type_filter,
            search_filter,
            limit,
            offset,
        )
        count_row = await self.connection.fetchrow(
            """
            SELECT COUNT(*) AS reports_count
            FROM content_reports r
            INNER JOIN users reporter ON reporter.id = r.reporter_id
            LEFT JOIN articles a ON a.id = r.article_id AND r.content_type = 'article'
            LEFT JOIN commentaries c ON c.id = r.comment_id
            LEFT JOIN articles report_article ON report_article.id = c.article_id
            WHERE (
                $1::text IS NULL
                OR r.status = $1
            )
              AND (
                $2::text IS NULL
                OR r.content_type = $2
            )
              AND (
                $3::text IS NULL
                OR r.reason ILIKE $3
                OR r.detail ILIKE $3
                OR reporter.username ILIKE $3
                OR a.slug ILIKE $3
                OR a.title ILIKE $3
                OR c.body ILIKE $3
                OR report_article.slug ILIKE $3
                OR report_article.title ILIKE $3
              )
            """,
            status_filter,
            type_filter,
            search_filter,
        )
        return ContentReportsInResponse(
            reports=[self._report_item_from_row(row) for row in rows],
            reports_count=count_row["reports_count"] if count_row else 0,
        )

    async def review_report(
        self,
        *,
        report_id: int,
        action: str,
        actor: User,
        note: str = "",
    ) -> Dict[str, object]:
        report = await self.connection.fetchrow(
            """
            SELECT
                r.id,
                r.content_type,
                r.article_id,
                r.comment_id,
                COALESCE(c.body, '') AS comment_body,
                COALESCE(a.content_status, c.content_status, '') AS content_status,
                COALESCE(a.author_id, c.author_id) AS author_id
            FROM content_reports r
            LEFT JOIN articles a ON a.id = r.article_id AND r.content_type = 'article'
            LEFT JOIN commentaries c ON c.id = r.comment_id
            WHERE r.id = $1
            """,
            report_id,
        )
        if not report:
            raise EntityDoesNotExist(
                "content report with id {0} does not exist".format(report_id),
            )

        new_report_status = "ignored" if action == "ignore" else "resolved"
        await self.connection.execute(
            """
            UPDATE content_reports
            SET status = $2,
                resolution_note = $3,
                resolved_by_id = $4,
                resolved_at = now()
            WHERE id = $1
            """,
            report_id,
            new_report_status,
            note,
            actor.id_,
        )

        to_status = report["content_status"]
        if action == "hide":
            to_status = "hidden"
            await self._set_content_status(
                content_type=report["content_type"],
                article_id=report["article_id"],
                comment_id=report["comment_id"],
                status=to_status,
            )

        return {
            "content_type": report["content_type"],
            "article_id": report["article_id"],
            "comment_id": report["comment_id"],
            "author_id": report["author_id"],
            "from_status": report["content_status"],
            "to_status": to_status,
            "report_status": new_report_status,
            "metadata": {"commentBody": report["comment_body"]},
        }

    async def create_audit_log(
        self,
        *,
        content_type: str,
        action: str,
        actor: Optional[User] = None,
        article_id: Optional[int] = None,
        comment_id: Optional[int] = None,
        from_status: str = "",
        to_status: str = "",
        note: str = "",
        metadata: Optional[Dict[str, object]] = None,
    ) -> None:
        await self.connection.execute(
            """
            INSERT INTO content_audit_logs (
                content_type,
                article_id,
                comment_id,
                actor_id,
                action,
                from_status,
                to_status,
                note,
                metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::json)
            """,
            content_type,
            article_id,
            comment_id,
            actor.id_ if actor else None,
            action,
            from_status,
            to_status,
            note,
            json.dumps(metadata or {}),
        )

    async def list_audit_logs(
        self,
        *,
        content_type: Optional[str] = "all",
        q: Optional[str] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> ContentAuditLogsInResponse:
        type_filter = None if content_type in (None, "", "all") else content_type
        search_filter = "%{0}%".format(q) if q else None
        rows = await self.connection.fetch(
            """
            SELECT
                l.id,
                l.content_type,
                l.comment_id,
                l.action,
                l.from_status,
                l.to_status,
                l.note,
                l.created_at,
                COALESCE(a.slug, report_article.slug, '') AS article_slug,
                COALESCE(a.title, report_article.title, '') AS article_title,
                COALESCE(NULLIF(c.body, ''), l.metadata ->> 'commentBody', '') AS comment_body,
                COALESCE(actor.username, '') AS actor_username
            FROM content_audit_logs l
            LEFT JOIN users actor ON actor.id = l.actor_id
            LEFT JOIN articles a ON a.id = l.article_id
            LEFT JOIN commentaries c ON c.id = l.comment_id
            LEFT JOIN articles report_article ON report_article.id = c.article_id
            WHERE (
                $1::text IS NULL
                OR l.content_type = $1
            )
              AND (
                $2::text IS NULL
                OR l.action ILIKE $2
                OR l.note ILIKE $2
                OR actor.username ILIKE $2
                OR a.slug ILIKE $2
                OR a.title ILIKE $2
                OR c.body ILIKE $2
                OR (l.metadata ->> 'commentBody') ILIKE $2
                OR report_article.slug ILIKE $2
                OR report_article.title ILIKE $2
              )
            ORDER BY l.created_at DESC
            LIMIT $3
            OFFSET $4
            """,
            type_filter,
            search_filter,
            limit,
            offset,
        )
        count_row = await self.connection.fetchrow(
            """
            SELECT COUNT(*) AS logs_count
            FROM content_audit_logs l
            LEFT JOIN users actor ON actor.id = l.actor_id
            LEFT JOIN articles a ON a.id = l.article_id
            LEFT JOIN commentaries c ON c.id = l.comment_id
            LEFT JOIN articles report_article ON report_article.id = c.article_id
            WHERE (
                $1::text IS NULL
                OR l.content_type = $1
            )
              AND (
                $2::text IS NULL
                OR l.action ILIKE $2
                OR l.note ILIKE $2
                OR actor.username ILIKE $2
                OR a.slug ILIKE $2
                OR a.title ILIKE $2
                OR c.body ILIKE $2
                OR (l.metadata ->> 'commentBody') ILIKE $2
                OR report_article.slug ILIKE $2
                OR report_article.title ILIKE $2
              )
            """,
            type_filter,
            search_filter,
        )
        return ContentAuditLogsInResponse(
            logs=[
                ContentAuditLogItem(
                    id=row["id"],
                    contentType=row["content_type"],
                    articleSlug=row["article_slug"],
                    articleTitle=row["article_title"],
                    commentId=row["comment_id"],
                    commentBody=row["comment_body"],
                    actorUsername=row["actor_username"],
                    action=row["action"],
                    fromStatus=row["from_status"],
                    toStatus=row["to_status"],
                    note=row["note"],
                    createdAt=row["created_at"],
                )
                for row in rows
            ],
            logs_count=count_row["logs_count"] if count_row else 0,
        )

    async def export_audit_logs_csv(
        self,
        *,
        content_type: Optional[str] = "all",
        q: Optional[str] = None,
    ) -> str:
        data = await self.list_audit_logs(
            content_type=content_type,
            q=q,
            limit=1000,
            offset=0,
        )
        lines = [
            "id,content_type,target,action,from_status,to_status,actor,created_at,note"
        ]
        for item in data.logs:
            target = item.article_title or item.article_slug or (
                "评论 #{0}".format(item.comment_id) if item.comment_id else ""
            )
            fields = [
                str(item.id),
                item.content_type,
                target,
                item.action,
                item.from_status,
                item.to_status,
                item.actor_username,
                item.created_at.isoformat(),
                item.note,
            ]
            escaped = [
                '"{0}"'.format(str(value or "").replace('"', '""'))
                for value in fields
            ]
            lines.append(",".join(escaped))
        return "\n".join(lines)

    async def create_notification(
        self,
        *,
        user_id: int,
        notification_type: str,
        title: str,
        body: str,
        content_type: str = "",
        article_id: Optional[int] = None,
        comment_id: Optional[int] = None,
    ) -> None:
        await self.connection.execute(
            """
            INSERT INTO user_notifications (
                user_id,
                notification_type,
                title,
                body,
                content_type,
                article_id,
                comment_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            user_id,
            notification_type,
            title,
            body,
            content_type,
            article_id,
            comment_id,
        )

    async def create_content_author_notification(
        self,
        *,
        content_type: str,
        article_id: Optional[int] = None,
        comment_id: Optional[int] = None,
        notification_type: str,
        title: str,
        body: str,
    ) -> None:
        author_row = await self.connection.fetchrow(
            """
            SELECT COALESCE(a.author_id, c.author_id) AS author_id
            FROM (SELECT $1::int AS article_id, $2::int AS comment_id) target
            LEFT JOIN articles a ON a.id = target.article_id
            LEFT JOIN commentaries c ON c.id = target.comment_id
            """,
            article_id,
            comment_id,
        )
        if not author_row or not author_row["author_id"]:
            return
        await self.create_notification(
            user_id=author_row["author_id"],
            notification_type=notification_type,
            title=title,
            body=body,
            content_type=content_type,
            article_id=article_id,
            comment_id=comment_id,
        )

    async def get_notifications(
        self,
        *,
        user: User,
        unread_only: bool = False,
        limit: int = 30,
        offset: int = 0,
    ) -> UserNotificationsInResponse:
        rows = await self.connection.fetch(
            """
            SELECT
                n.id,
                n.notification_type,
                n.title,
                n.body,
                n.is_read,
                n.content_type,
                n.comment_id,
                n.created_at,
                n.read_at,
                COALESCE(a.slug, report_article.slug, '') AS article_slug,
                COALESCE(a.title, report_article.title, '') AS article_title
            FROM user_notifications n
            LEFT JOIN articles a ON a.id = n.article_id
            LEFT JOIN commentaries c ON c.id = n.comment_id
            LEFT JOIN articles report_article ON report_article.id = c.article_id
            WHERE n.user_id = $1
              AND (
                $2 = FALSE
                OR n.is_read = FALSE
              )
            ORDER BY n.created_at DESC
            LIMIT $3
            OFFSET $4
            """,
            user.id_,
            unread_only,
            limit,
            offset,
        )
        count_row = await self.connection.fetchrow(
            """
            SELECT COUNT(*) AS notifications_count
            FROM user_notifications
            WHERE user_id = $1
              AND (
                $2 = FALSE
                OR is_read = FALSE
              )
            """,
            user.id_,
            unread_only,
        )
        return UserNotificationsInResponse(
            notifications=[
                UserNotificationItem(
                    id=row["id"],
                    notificationType=row["notification_type"],
                    title=row["title"],
                    body=row["body"],
                    isRead=row["is_read"],
                    contentType=row["content_type"],
                    articleSlug=row["article_slug"],
                    articleTitle=row["article_title"],
                    commentId=row["comment_id"],
                    createdAt=row["created_at"],
                    readAt=row["read_at"],
                )
                for row in rows
            ],
            notifications_count=count_row["notifications_count"] if count_row else 0,
        )

    async def mark_notification_read(self, *, notification_id: int, user: User) -> None:
        result = await self.connection.execute(
            """
            UPDATE user_notifications
            SET is_read = TRUE,
                read_at = now()
            WHERE id = $1
              AND user_id = $2
            """,
            notification_id,
            user.id_,
        )
        if result == "UPDATE 0":
            raise EntityDoesNotExist(
                "notification with id {0} does not exist".format(notification_id),
            )

    async def get_user_content(
        self,
        *,
        user: User,
        content_type: str = "articles",
        content_status: str = "all",
        q: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> UserContentInResponse:
        status_filter = None if content_status in ("", "all", None) else content_status
        search_filter = "%{0}%".format(q) if q else None
        article_rows = await self.connection.fetch(
            """
            SELECT
                a.slug,
                a.title,
                a.description,
                a.body,
                a.content_status,
                a.created_at,
                a.updated_at,
                COALESCE(aml.review_status, '') AS latest_review_status,
                COALESCE(aml.review_note, '') AS latest_review_note,
                COALESCE(cal.action, '') AS latest_action,
                cal.created_at AS latest_action_at
            FROM articles a
            LEFT JOIN LATERAL (
                SELECT review_status, review_note
                FROM article_moderation_logs
                WHERE article_id = a.id
                ORDER BY created_at DESC
                LIMIT 1
            ) aml ON TRUE
            LEFT JOIN LATERAL (
                SELECT action, created_at
                FROM content_audit_logs
                WHERE article_id = a.id
                  AND comment_id IS NULL
                ORDER BY created_at DESC
                LIMIT 1
            ) cal ON TRUE
            WHERE a.author_id = $1
              AND (
                $2::text IS NULL
                OR a.content_status = $2
              )
              AND (
                $3::text IS NULL
                OR a.title ILIKE $3
                OR a.description ILIKE $3
                OR a.body ILIKE $3
              )
            ORDER BY a.updated_at DESC
            LIMIT $4
            OFFSET $5
            """,
            user.id_,
            status_filter,
            search_filter,
            limit,
            offset,
        )
        comment_rows = await self.connection.fetch(
            """
            SELECT
                c.id,
                c.body,
                a.slug AS article_slug,
                a.title AS article_title,
                c.content_status,
                c.created_at,
                c.updated_at,
                COALESCE(cml.review_status, '') AS latest_review_status,
                COALESCE(cml.review_note, '') AS latest_review_note,
                COALESCE(cal.action, '') AS latest_action,
                cal.created_at AS latest_action_at
            FROM commentaries c
            INNER JOIN articles a ON a.id = c.article_id
            LEFT JOIN LATERAL (
                SELECT review_status, review_note
                FROM comment_moderation_logs
                WHERE comment_id = c.id
                ORDER BY created_at DESC
                LIMIT 1
            ) cml ON TRUE
            LEFT JOIN LATERAL (
                SELECT action, created_at
                FROM content_audit_logs
                WHERE comment_id = c.id
                ORDER BY created_at DESC
                LIMIT 1
            ) cal ON TRUE
            WHERE c.author_id = $1
              AND (
                $2::text IS NULL
                OR c.content_status = $2
              )
              AND (
                $3::text IS NULL
                OR c.body ILIKE $3
                OR a.slug ILIKE $3
                OR a.title ILIKE $3
              )
            ORDER BY c.updated_at DESC
            LIMIT $4
            OFFSET $5
            """,
            user.id_,
            status_filter,
            search_filter,
            limit,
            offset,
        )
        articles_count_row = await self.connection.fetchrow(
            """
            SELECT COUNT(*) AS count
            FROM articles a
            WHERE a.author_id = $1
              AND (
                $2::text IS NULL
                OR a.content_status = $2
              )
              AND (
                $3::text IS NULL
                OR a.title ILIKE $3
                OR a.description ILIKE $3
                OR a.body ILIKE $3
              )
            """,
            user.id_,
            status_filter,
            search_filter,
        )
        comments_count_row = await self.connection.fetchrow(
            """
            SELECT COUNT(*) AS count
            FROM commentaries c
            INNER JOIN articles a ON a.id = c.article_id
            WHERE c.author_id = $1
              AND (
                $2::text IS NULL
                OR c.content_status = $2
              )
              AND (
                $3::text IS NULL
                OR c.body ILIKE $3
                OR a.slug ILIKE $3
                OR a.title ILIKE $3
              )
            """,
            user.id_,
            status_filter,
            search_filter,
        )
        counts = await self.connection.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE content_status = 'pending') AS pending_articles,
                COUNT(*) FILTER (WHERE content_status = 'hidden') AS hidden_articles
            FROM articles
            WHERE author_id = $1
            """,
            user.id_,
        )
        comment_counts = await self.connection.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE content_status = 'pending') AS pending_comments,
                COUNT(*) FILTER (WHERE content_status = 'hidden') AS hidden_comments
            FROM commentaries
            WHERE author_id = $1
            """,
            user.id_,
        )
        return UserContentInResponse(
            overview=UserContentOverview(
                pendingArticles=counts["pending_articles"] if counts else 0,
                hiddenArticles=counts["hidden_articles"] if counts else 0,
                pendingComments=comment_counts["pending_comments"] if comment_counts else 0,
                hiddenComments=comment_counts["hidden_comments"] if comment_counts else 0,
            ),
            articles=[
                UserContentArticleItem(
                    slug=row["slug"],
                    title=row["title"],
                    description=row["description"],
                    body=row["body"],
                    tagList=await self._get_tags_for_article(row["slug"]),
                    contentStatus=row["content_status"],
                    latestReviewStatus=row["latest_review_status"],
                    latestReviewNote=row["latest_review_note"],
                    latestAction=row["latest_action"],
                    latestActionAt=row["latest_action_at"],
                    createdAt=row["created_at"],
                    updatedAt=row["updated_at"],
                )
                for row in article_rows
            ],
            articlesCount=articles_count_row["count"] if articles_count_row else 0,
            comments=[
                UserContentCommentItem(
                    id=row["id"],
                    body=row["body"],
                    articleSlug=row["article_slug"],
                    articleTitle=row["article_title"],
                    contentStatus=row["content_status"],
                    latestReviewStatus=row["latest_review_status"],
                    latestReviewNote=row["latest_review_note"],
                    latestAction=row["latest_action"],
                    latestActionAt=row["latest_action_at"],
                    createdAt=row["created_at"],
                    updatedAt=row["updated_at"],
                )
                for row in comment_rows
            ],
            commentsCount=comments_count_row["count"] if comments_count_row else 0,
            contentType=content_type,
        )

    async def _get_tags_for_article(self, slug: str) -> List[str]:
        rows = await self.connection.fetch(
            """
            SELECT t.tag
            FROM tags t
            INNER JOIN articles_to_tags att
                ON t.tag = att.tag
            INNER JOIN articles a
                ON a.id = att.article_id
            WHERE a.slug = $1
            ORDER BY t.tag
            """,
            slug,
        )
        return [row["tag"] for row in rows]

    async def _set_content_status(
        self,
        *,
        content_type: str,
        article_id: Optional[int],
        comment_id: Optional[int],
        status: str,
    ) -> None:
        if content_type == "article":
            await self.connection.execute(
                "UPDATE articles SET content_status = $2 WHERE id = $1",
                article_id,
                status,
            )
            return
        await self.connection.execute(
            "UPDATE commentaries SET content_status = $2 WHERE id = $1",
            comment_id,
            status,
        )

    def _report_item_from_row(self, row) -> ContentReportItem:
        return ContentReportItem(
            id=row["id"],
            contentType=row["content_type"],
            reason=row["reason"],
            detail=row["detail"],
            status=row["status"],
            reporterUsername=row["reporter_username"],
            authorUsername=row["author_username"],
            articleSlug=row["article_slug"],
            articleTitle=row["article_title"],
            commentId=row["comment_id"],
            commentBody=row["comment_body"],
            contentStatus=row["content_status"],
            resolutionNote=row["resolution_note"],
            resolvedByUsername=row["resolved_by_username"],
            createdAt=row["created_at"],
            resolvedAt=row["resolved_at"],
        )
