from typing import List

from pydantic import Field

from app.models.domain.comments import Comment
from app.models.schemas.rwschema import RWSchema


class ListOfCommentsInResponse(RWSchema):
    comments: List[Comment]


class CommentInResponse(RWSchema):
    comment: Comment


class CommentInCreate(RWSchema):
    body: str


class CommentInUpdate(RWSchema):
    body: str
    submit_for_review: bool = Field(False, alias="submitForReview")


class CommentModeration(RWSchema):
    allowed: bool
    category: str
    severity: str
    reason: str
    suggested_revision: str = Field("", alias="suggestedRevision")
    confidence: float
    model: str = ""


class CommentModerationInResponse(RWSchema):
    moderation: CommentModeration
