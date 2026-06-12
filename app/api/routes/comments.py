from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from starlette import status

from app.api.dependencies.articles import get_article_by_slug_from_path
from app.api.dependencies.articles import get_article_by_slug_for_author_from_path
from app.api.dependencies.ai import get_comment_moderation_service
from app.api.dependencies.authentication import get_current_user_authorizer
from app.api.dependencies.comments import (
    check_comment_modification_permissions,
    get_comment_by_id_for_author_from_path,
    get_comment_by_id_from_path,
)
from app.api.dependencies.database import get_repository
from app.db.repositories.comments import CommentsRepository
from app.db.repositories.governance import GovernanceRepository
from app.models.domain.articles import Article
from app.models.domain.comments import Comment
from app.models.domain.users import User
from app.models.schemas.comments import (
    CommentInCreate,
    CommentInResponse,
    CommentInUpdate,
    CommentModerationInResponse,
    ListOfCommentsInResponse,
)
from app.models.schemas.governance import (
    ContentReportInCreate,
    ContentReportInResponse,
)
from app.services.ai.comment_moderation import CommentModerationService
from app.services.ai.errors import AIServiceError

router = APIRouter()


@router.get(
    "",
    response_model=ListOfCommentsInResponse,
    name="comments:get-comments-for-article",
)
async def list_comments_for_article(
    article: Article = Depends(get_article_by_slug_from_path),
    user: Optional[User] = Depends(get_current_user_authorizer(required=False)),
    comments_repo: CommentsRepository = Depends(get_repository(CommentsRepository)),
) -> ListOfCommentsInResponse:
    comments = await comments_repo.get_comments_for_article(article=article, user=user)
    return ListOfCommentsInResponse(comments=comments)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CommentInResponse,
    name="comments:create-comment-for-article",
)
async def create_comment_for_article(
    comment_create: CommentInCreate = Body(..., embed=True, alias="comment"),
    article: Article = Depends(get_article_by_slug_from_path),
    user: User = Depends(get_current_user_authorizer()),
    comments_repo: CommentsRepository = Depends(get_repository(CommentsRepository)),
    moderation_service: CommentModerationService = Depends(
        get_comment_moderation_service,
    ),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> CommentInResponse:
    moderation = None
    content_status = "visible"
    if moderation_service.enabled_for_comment_creation:
        try:
            moderation = await moderation_service.moderate_comment(
                article=article,
                user=user,
                body=comment_create.body,
            )
        except AIServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI comment moderation is unavailable: {0}".format(exc),
            ) from exc

        if not moderation.allowed:
            content_status = "pending"

    comment = await comments_repo.create_comment_for_article(
        body=comment_create.body,
        article=article,
        user=user,
        content_status=content_status,
    )
    if moderation:
        await comments_repo.create_moderation_log(
            body=comment_create.body,
            article=article,
            user=user,
            moderation=moderation,
            comment=comment,
            review_status="approved" if content_status == "visible" else "pending",
        )
        if content_status == "pending":
            await governance_repo.create_audit_log(
                content_type="comment",
                article_id=article.id_,
                comment_id=comment.id_,
                action="ai_pending_review",
                from_status="draft",
                to_status="pending",
                note="AI review marked this comment for manual review.",
                metadata={"category": moderation.category, "severity": moderation.severity},
            )
            await governance_repo.create_notification(
                user_id=user.id_,
                notification_type="comment_pending_review",
                title="评论已进入待审核",
                body="AI 初审认为评论需要人工复核，通过后会公开显示。",
                content_type="comment",
                article_id=article.id_,
                comment_id=comment.id_,
            )
    return CommentInResponse(comment=comment)


@router.post(
    "/ai/moderate",
    response_model=CommentModerationInResponse,
    name="comments:moderate-comment-for-article",
)
async def moderate_comment_for_article(
    comment_create: CommentInCreate = Body(..., embed=True, alias="comment"),
    article: Article = Depends(get_article_by_slug_from_path),
    user: User = Depends(get_current_user_authorizer()),
    moderation_service: CommentModerationService = Depends(
        get_comment_moderation_service,
    ),
) -> CommentModerationInResponse:
    try:
        moderation = await moderation_service.moderate_comment(
            article=article,
            user=user,
            body=comment_create.body,
        )
    except AIServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI comment moderation is unavailable: {0}".format(exc),
        ) from exc

    return CommentModerationInResponse(moderation=moderation)


@router.post(
    "/{comment_id}/report",
    response_model=ContentReportInResponse,
    name="comments:report-comment",
)
async def report_comment(
    report: ContentReportInCreate = Body(..., embed=True, alias="report"),
    article: Article = Depends(get_article_by_slug_from_path),
    comment: Comment = Depends(get_comment_by_id_from_path),
    user: User = Depends(get_current_user_authorizer()),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> ContentReportInResponse:
    return await governance_repo.create_comment_report(
        article=article,
        comment=comment,
        reporter=user,
        reason=report.reason,
        detail=report.detail,
    )


@router.post(
    "/{comment_id}/like",
    response_model=CommentInResponse,
    name="comments:like-comment",
)
async def like_comment(
    comment: Comment = Depends(get_comment_by_id_from_path),
    user: User = Depends(get_current_user_authorizer()),
    comments_repo: CommentsRepository = Depends(get_repository(CommentsRepository)),
) -> CommentInResponse:
    if comment.liked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Comment is already liked.",
        )
    await comments_repo.add_like_to_comment(comment=comment, user=user)
    return CommentInResponse(
        comment=comment.copy(
            update={
                "liked": True,
                "likes_count": comment.likes_count + 1,
            },
        ),
    )


@router.delete(
    "/{comment_id}/like",
    response_model=CommentInResponse,
    name="comments:unlike-comment",
)
async def unlike_comment(
    comment: Comment = Depends(get_comment_by_id_from_path),
    user: User = Depends(get_current_user_authorizer()),
    comments_repo: CommentsRepository = Depends(get_repository(CommentsRepository)),
) -> CommentInResponse:
    if not comment.liked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Comment is not liked.",
        )
    await comments_repo.remove_like_from_comment(comment=comment, user=user)
    return CommentInResponse(
        comment=comment.copy(
            update={
                "liked": False,
                "likes_count": max(0, comment.likes_count - 1),
            },
        ),
    )


@router.put(
    "/{comment_id}",
    response_model=CommentInResponse,
    name="comments:update-comment-for-article",
    dependencies=[Depends(check_comment_modification_permissions)],
)
async def update_comment_for_article(
    comment_update: CommentInUpdate = Body(..., embed=True, alias="comment"),
    article: Article = Depends(get_article_by_slug_for_author_from_path),
    comment: Comment = Depends(get_comment_by_id_for_author_from_path),
    user: User = Depends(get_current_user_authorizer()),
    comments_repo: CommentsRepository = Depends(get_repository(CommentsRepository)),
    moderation_service: CommentModerationService = Depends(
        get_comment_moderation_service,
    ),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> CommentInResponse:
    updated_comment = await comments_repo.update_comment(
        comment=comment,
        body=comment_update.body,
    )
    if comment_update.submit_for_review:
        moderation = None
        if moderation_service.enabled_for_comment_creation:
            try:
                moderation = await moderation_service.moderate_comment(
                    article=article,
                    user=user,
                    body=comment_update.body,
                )
            except AIServiceError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="AI comment moderation is unavailable: {0}".format(exc),
                ) from exc
            await comments_repo.create_moderation_log(
                body=comment_update.body,
                article=article,
                user=user,
                moderation=moderation,
                comment=updated_comment,
                review_status="pending",
            )
        await comments_repo.set_comment_content_status(
            comment_id=updated_comment.id_,
            status="pending",
        )
        updated_comment.content_status = "pending"
        await governance_repo.create_audit_log(
            content_type="comment",
            article_id=article.id_,
            comment_id=updated_comment.id_,
            actor=user,
            action="author_resubmit",
            from_status=comment.content_status,
            to_status="pending",
            note="作者已修改并重新提交评论审核。",
            metadata={
                "commentBody": updated_comment.body,
                **(
                    {"category": moderation.category, "severity": moderation.severity}
                    if moderation
                    else {}
                ),
            },
        )
    return CommentInResponse(comment=updated_comment)


@router.delete(
    "/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    name="comments:delete-comment-from-article",
    dependencies=[Depends(check_comment_modification_permissions)],
    response_class=Response,
)
async def delete_comment_from_article(
    comment: Comment = Depends(get_comment_by_id_from_path),
    comments_repo: CommentsRepository = Depends(get_repository(CommentsRepository)),
) -> None:
    await comments_repo.delete_comment(comment=comment)
