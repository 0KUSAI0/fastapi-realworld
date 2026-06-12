import datetime
from typing import List, Optional

from pydantic import Field

from app.models.schemas.articles import ArticleForResponse
from app.models.schemas.rwschema import RWSchema


class AdminOverviewStats(RWSchema):
    users_count: int = 0
    articles_count: int = 0
    articles_visible: int = 0
    articles_pending: int = 0
    articles_hidden: int = 0
    comments_count: int = 0
    comments_visible: int = 0
    comments_pending: int = 0
    comments_hidden: int = 0
    moderation_total: int = 0
    moderation_pending: int = 0
    moderation_blocked: int = 0
    article_moderation_total: int = 0
    article_moderation_pending: int = 0
    article_moderation_blocked: int = 0
    high_risk: int = Field(0, alias="highRisk")


class AdminOverviewInResponse(RWSchema):
    stats: AdminOverviewStats


class AdminArticlesInResponse(RWSchema):
    articles: List[ArticleForResponse]
    articles_count: int


class AdminCommentItem(RWSchema):
    id: int
    body: str
    content_status: str
    article_slug: str
    article_title: str
    author_username: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


class AdminCommentsInResponse(RWSchema):
    comments: List[AdminCommentItem]
    comments_count: int


class AdminCommentThreadItem(RWSchema):
    article_slug: str
    article_title: str
    article_content_status: str = Field(..., alias="articleContentStatus")
    comments_count: int = Field(..., alias="commentsCount")
    visible_count: int = Field(..., alias="visibleCount")
    hidden_count: int = Field(..., alias="hiddenCount")
    pending_count: int = Field(..., alias="pendingCount")
    latest_comment_body: str = Field("", alias="latestCommentBody")
    latest_comment_at: Optional[datetime.datetime] = Field(None, alias="latestCommentAt")


class AdminCommentThreadsInResponse(RWSchema):
    threads: List[AdminCommentThreadItem]
    threads_count: int = Field(..., alias="threadsCount")


class ModerationStats(RWSchema):
    total: int = 0
    blocked: int = 0
    pending: int = 0
    high_risk: int = Field(0, alias="highRisk")


class ModerationQueueItem(RWSchema):
    id: int
    content_type: str = Field("comment", alias="contentType")
    content_id: Optional[int] = Field(None, alias="contentId")
    article_slug: str = ""
    article_title: str = ""
    title: str = ""
    body: str
    author_username: str = ""
    allowed: bool
    category: str
    severity: str
    reason: str
    suggested_revision: str = Field("", alias="suggestedRevision")
    confidence: float
    content_score: Optional[int] = Field(None, alias="contentScore")
    risk_labels: List[str] = Field(default_factory=list, alias="riskLabels")
    suggestions: List[str] = Field(default_factory=list)
    model: str
    content_status: str = Field(..., alias="contentStatus")
    review_status: str = Field(..., alias="reviewStatus")
    created_at: datetime.datetime


class ModerationDashboardInResponse(RWSchema):
    stats: ModerationStats
    items: List[ModerationQueueItem]
    items_count: int


class ModerationReviewInCreate(RWSchema):
    action: str
    note: str = ""


class ContentStatusInUpdate(RWSchema):
    status: str
    note: str = ""
