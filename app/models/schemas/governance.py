import datetime
from typing import List, Optional

from pydantic import Field

from app.models.schemas.rwschema import RWSchema


class ContentReportInCreate(RWSchema):
    reason: str
    detail: str = ""


class ContentReportInResponse(RWSchema):
    id: int
    content_type: str
    reason: str
    detail: str
    status: str
    created_at: datetime.datetime


class ContentReportItem(RWSchema):
    id: int
    content_type: str = Field(..., alias="contentType")
    reason: str
    detail: str
    status: str
    reporter_username: str = Field("", alias="reporterUsername")
    author_username: str = Field("", alias="authorUsername")
    article_slug: str = Field("", alias="articleSlug")
    article_title: str = Field("", alias="articleTitle")
    comment_id: Optional[int] = Field(None, alias="commentId")
    comment_body: str = Field("", alias="commentBody")
    content_status: str = Field("", alias="contentStatus")
    resolution_note: str = Field("", alias="resolutionNote")
    resolved_by_username: str = Field("", alias="resolvedByUsername")
    created_at: datetime.datetime
    resolved_at: Optional[datetime.datetime] = Field(None, alias="resolvedAt")


class ContentReportsInResponse(RWSchema):
    reports: List[ContentReportItem]
    reports_count: int


class ContentReportReviewInCreate(RWSchema):
    action: str
    note: str = ""


class ContentAuditLogItem(RWSchema):
    id: int
    content_type: str = Field(..., alias="contentType")
    article_slug: str = Field("", alias="articleSlug")
    article_title: str = Field("", alias="articleTitle")
    comment_id: Optional[int] = Field(None, alias="commentId")
    comment_body: str = Field("", alias="commentBody")
    actor_username: str = Field("", alias="actorUsername")
    action: str
    from_status: str = Field("", alias="fromStatus")
    to_status: str = Field("", alias="toStatus")
    note: str
    created_at: datetime.datetime


class ContentAuditLogsInResponse(RWSchema):
    logs: List[ContentAuditLogItem]
    logs_count: int


class UserNotificationItem(RWSchema):
    id: int
    notification_type: str = Field(..., alias="notificationType")
    title: str
    body: str
    is_read: bool = Field(..., alias="isRead")
    content_type: str = Field("", alias="contentType")
    article_slug: str = Field("", alias="articleSlug")
    article_title: str = Field("", alias="articleTitle")
    comment_id: Optional[int] = Field(None, alias="commentId")
    created_at: datetime.datetime
    read_at: Optional[datetime.datetime] = Field(None, alias="readAt")


class UserNotificationsInResponse(RWSchema):
    notifications: List[UserNotificationItem]
    notifications_count: int


class UserContentArticleItem(RWSchema):
    slug: str
    title: str
    description: str
    body: str
    tags: List[str] = Field(default_factory=list, alias="tagList")
    content_status: str = Field("", alias="contentStatus")
    latest_review_status: str = Field("", alias="latestReviewStatus")
    latest_review_note: str = Field("", alias="latestReviewNote")
    latest_action: str = Field("", alias="latestAction")
    latest_action_at: Optional[datetime.datetime] = Field(None, alias="latestActionAt")
    created_at: datetime.datetime
    updated_at: datetime.datetime


class UserContentCommentItem(RWSchema):
    id: int
    body: str
    article_slug: str = Field("", alias="articleSlug")
    article_title: str = Field("", alias="articleTitle")
    content_status: str = Field("", alias="contentStatus")
    latest_review_status: str = Field("", alias="latestReviewStatus")
    latest_review_note: str = Field("", alias="latestReviewNote")
    latest_action: str = Field("", alias="latestAction")
    latest_action_at: Optional[datetime.datetime] = Field(None, alias="latestActionAt")
    created_at: datetime.datetime
    updated_at: datetime.datetime


class UserContentOverview(RWSchema):
    pending_articles: int = Field(0, alias="pendingArticles")
    hidden_articles: int = Field(0, alias="hiddenArticles")
    pending_comments: int = Field(0, alias="pendingComments")
    hidden_comments: int = Field(0, alias="hiddenComments")


class UserContentInResponse(RWSchema):
    overview: UserContentOverview
    articles: List[UserContentArticleItem]
    articles_count: int = Field(0, alias="articlesCount")
    comments: List[UserContentCommentItem]
    comments_count: int = Field(0, alias="commentsCount")
    content_type: str = Field("articles", alias="contentType")
