from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse
from starlette import status

from app.api.dependencies.authentication import get_current_user_authorizer
from app.api.dependencies.database import get_repository
from app.core.config import get_app_settings
from app.core.settings.app import AppSettings
from app.db.errors import EntityDoesNotExist
from app.db.repositories.admin import AdminRepository
from app.db.repositories.comments import CommentsRepository
from app.db.repositories.governance import GovernanceRepository
from app.models.domain.users import User
from app.models.schemas.admin import (
    AdminArticlesInResponse,
    AdminCommentsInResponse,
    AdminCommentThreadsInResponse,
    AdminOverviewInResponse,
    ContentStatusInUpdate,
    ModerationDashboardInResponse,
    ModerationReviewInCreate,
)
from app.models.schemas.articles import ArticleInResponse, ArticleForResponse
from app.models.schemas.governance import (
    ContentAuditLogsInResponse,
    ContentReportReviewInCreate,
    ContentReportsInResponse,
)
from app.resources import strings

router = APIRouter()

CONTENT_STATUSES = {"visible", "hidden", "pending"}
REVIEW_STATUSES = {"pending", "approved", "rejected", "all"}
REVIEW_ACTIONS = {"approve", "reject"}
REPORT_STATUSES = {"pending", "resolved", "ignored", "all"}
REPORT_TYPES = {"article", "comment", "all"}
REPORT_ACTIONS = {"resolve", "ignore", "hide"}


def get_admin_user(
    user: User = Depends(get_current_user_authorizer()),
    settings: AppSettings = Depends(get_app_settings),
) -> User:
    if settings.admin_usernames and user.username not in settings.admin_usernames:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges are required.",
        )
    return user


@router.get(
    "/overview",
    response_model=AdminOverviewInResponse,
    name="admin:get-overview",
)
async def get_admin_overview(
    user: User = Depends(get_admin_user),
    admin_repo: AdminRepository = Depends(get_repository(AdminRepository)),
) -> AdminOverviewInResponse:
    return await admin_repo.get_overview()


@router.get(
    "/reports",
    response_model=ContentReportsInResponse,
    name="admin:list-content-reports",
)
async def list_content_reports(
    status_filter: str = Query("pending", alias="status"),
    content_type: str = Query("all", alias="type"),
    q: str = "",
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> ContentReportsInResponse:
    _validate_report_status(status_filter)
    _validate_report_type(content_type)
    return await governance_repo.list_reports(
        status=status_filter,
        content_type=content_type,
        q=q or None,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/reports/{report_id}/review",
    response_model=ContentReportsInResponse,
    name="admin:review-content-report",
)
async def review_content_report(
    report_id: int,
    review: ContentReportReviewInCreate = Body(...),
    user: User = Depends(get_admin_user),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> ContentReportsInResponse:
    _validate_report_action(review.action)
    try:
        transition = await governance_repo.review_report(
            report_id=report_id,
            action=review.action,
            actor=user,
            note=review.note,
        )
    except EntityDoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Content report does not exist.",
        )
    await _record_transition(
        governance_repo=governance_repo,
        actor=user,
        transition=transition,
        action="report_{0}".format(review.action),
        note=review.note,
    )
    return await governance_repo.list_reports()


@router.get(
    "/audit-logs",
    response_model=ContentAuditLogsInResponse,
    name="admin:list-content-audit-logs",
)
async def list_content_audit_logs(
    content_type: str = Query("all", alias="type"),
    q: str = "",
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> ContentAuditLogsInResponse:
    _validate_report_type(content_type)
    return await governance_repo.list_audit_logs(
        content_type=content_type,
        q=q or None,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/audit-logs/export",
    response_class=PlainTextResponse,
    name="admin:export-content-audit-logs",
)
async def export_content_audit_logs(
    content_type: str = Query("all", alias="type"),
    q: str = "",
    user: User = Depends(get_admin_user),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> PlainTextResponse:
    _validate_report_type(content_type)
    csv_text = await governance_repo.export_audit_logs_csv(
        content_type=content_type,
        q=q or None,
    )
    return PlainTextResponse(
        csv_text,
        headers={
            "Content-Disposition": 'attachment; filename="audit-logs.csv"',
        },
    )


@router.get(
    "/moderation",
    response_model=ModerationDashboardInResponse,
    name="admin:get-moderation-dashboard",
)
async def get_moderation_dashboard(
    status_filter: str = Query("pending", alias="status"),
    q: str = "",
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    comments_repo: CommentsRepository = Depends(get_repository(CommentsRepository)),
) -> ModerationDashboardInResponse:
    _validate_review_status(status_filter)
    return await comments_repo.get_moderation_dashboard(
        review_status=status_filter,
        q=q or None,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/moderation/comments",
    response_model=ModerationDashboardInResponse,
    name="admin:get-comment-moderation-dashboard",
)
async def get_comment_moderation_dashboard(
    status_filter: str = Query("pending", alias="status"),
    q: str = "",
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    comments_repo: CommentsRepository = Depends(get_repository(CommentsRepository)),
) -> ModerationDashboardInResponse:
    _validate_review_status(status_filter)
    return await comments_repo.get_moderation_dashboard(
        review_status=status_filter,
        q=q or None,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/moderation/articles",
    response_model=ModerationDashboardInResponse,
    name="admin:get-article-moderation-dashboard",
)
async def get_article_moderation_dashboard(
    status_filter: str = Query("pending", alias="status"),
    q: str = "",
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    admin_repo: AdminRepository = Depends(get_repository(AdminRepository)),
) -> ModerationDashboardInResponse:
    _validate_review_status(status_filter)
    return await admin_repo.get_article_moderation_dashboard(
        review_status=status_filter,
        q=q or None,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/moderation/{log_id}/review",
    response_model=ModerationDashboardInResponse,
    name="admin:review-moderation-log",
)
async def review_moderation_log(
    log_id: int,
    review: ModerationReviewInCreate = Body(...),
    user: User = Depends(get_admin_user),
    comments_repo: CommentsRepository = Depends(get_repository(CommentsRepository)),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> ModerationDashboardInResponse:
    _validate_review_action(review.action)
    try:
        transition = await comments_repo.review_moderation_log(
            log_id=log_id,
            action=review.action,
            note=review.note,
        )
    except EntityDoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Moderation log does not exist.",
        )
    await _record_transition(
        governance_repo=governance_repo,
        actor=user,
        transition=transition,
        action="moderation_{0}".format(review.action),
        note=review.note,
    )
    return await comments_repo.get_moderation_dashboard()


@router.post(
    "/moderation/comments/{log_id}/review",
    response_model=ModerationDashboardInResponse,
    name="admin:review-comment-moderation-log",
)
async def review_comment_moderation_log(
    log_id: int,
    review: ModerationReviewInCreate = Body(...),
    user: User = Depends(get_admin_user),
    comments_repo: CommentsRepository = Depends(get_repository(CommentsRepository)),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> ModerationDashboardInResponse:
    _validate_review_action(review.action)
    try:
        transition = await comments_repo.review_moderation_log(
            log_id=log_id,
            action=review.action,
            note=review.note,
        )
    except EntityDoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Moderation log does not exist.",
        )
    await _record_transition(
        governance_repo=governance_repo,
        actor=user,
        transition=transition,
        action="moderation_{0}".format(review.action),
        note=review.note,
    )
    return await comments_repo.get_moderation_dashboard()


@router.post(
    "/moderation/articles/{log_id}/review",
    response_model=ModerationDashboardInResponse,
    name="admin:review-article-moderation-log",
)
async def review_article_moderation_log(
    log_id: int,
    review: ModerationReviewInCreate = Body(...),
    user: User = Depends(get_admin_user),
    admin_repo: AdminRepository = Depends(get_repository(AdminRepository)),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> ModerationDashboardInResponse:
    _validate_review_action(review.action)
    try:
        transition = await admin_repo.review_article_moderation_log(
            log_id=log_id,
            action=review.action,
            note=review.note,
        )
    except EntityDoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article moderation log does not exist.",
        )
    await _record_transition(
        governance_repo=governance_repo,
        actor=user,
        transition=transition,
        action="moderation_{0}".format(review.action),
        note=review.note,
    )
    return await admin_repo.get_article_moderation_dashboard()


@router.get(
    "/articles",
    response_model=AdminArticlesInResponse,
    name="admin:list-articles",
)
async def list_admin_articles(
    q: str = "",
    status_filter: str = Query("visible", alias="status"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    admin_repo: AdminRepository = Depends(get_repository(AdminRepository)),
) -> AdminArticlesInResponse:
    _validate_content_status(status_filter, allow_all=True)
    return await admin_repo.list_articles(
        requested_user=user,
        q=q or None,
        content_status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/articles/{slug}",
    response_model=ArticleInResponse,
    name="admin:get-article",
)
async def get_admin_article(
    slug: str,
    user: User = Depends(get_admin_user),
    admin_repo: AdminRepository = Depends(get_repository(AdminRepository)),
) -> ArticleInResponse:
    try:
        article = await admin_repo.get_article(slug=slug, requested_user=user)
    except EntityDoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=strings.ARTICLE_DOES_NOT_EXIST_ERROR,
        )
    return ArticleInResponse(article=ArticleForResponse.from_orm(article))


@router.delete(
    "/articles/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    name="admin:delete-article",
    response_class=Response,
)
async def delete_admin_article(
    slug: str,
    user: User = Depends(get_admin_user),
    admin_repo: AdminRepository = Depends(get_repository(AdminRepository)),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> None:
    try:
        transition = await admin_repo.set_article_status(
            slug=slug,
            content_status="hidden",
        )
    except EntityDoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=strings.ARTICLE_DOES_NOT_EXIST_ERROR,
        )
    await _record_transition(
        governance_repo=governance_repo,
        actor=user,
        transition=transition,
        action="manual_hide",
        note="",
    )


@router.put(
    "/articles/{slug}/status",
    status_code=status.HTTP_204_NO_CONTENT,
    name="admin:update-article-status",
    response_class=Response,
)
async def update_admin_article_status(
    slug: str,
    update: ContentStatusInUpdate = Body(...),
    user: User = Depends(get_admin_user),
    admin_repo: AdminRepository = Depends(get_repository(AdminRepository)),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> None:
    _validate_content_status(update.status)
    try:
        transition = await admin_repo.set_article_status(
            slug=slug,
            content_status=update.status,
        )
    except EntityDoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=strings.ARTICLE_DOES_NOT_EXIST_ERROR,
        )
    await _record_transition(
        governance_repo=governance_repo,
        actor=user,
        transition=transition,
        action="manual_status_update",
        note=update.note,
    )


@router.get(
    "/comments",
    response_model=AdminCommentsInResponse,
    name="admin:list-comments",
)
async def list_admin_comments(
    q: str = "",
    status_filter: str = Query("visible", alias="status"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    admin_repo: AdminRepository = Depends(get_repository(AdminRepository)),
) -> AdminCommentsInResponse:
    _validate_content_status(status_filter, allow_all=True)
    return await admin_repo.list_comments(
        q=q or None,
        content_status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/comment-threads",
    response_model=AdminCommentThreadsInResponse,
    name="admin:list-comment-threads",
)
async def list_admin_comment_threads(
    q: str = "",
    status_filter: str = Query("all", alias="status"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    admin_repo: AdminRepository = Depends(get_repository(AdminRepository)),
) -> AdminCommentThreadsInResponse:
    _validate_content_status(status_filter, allow_all=True)
    return await admin_repo.list_comment_threads(
        q=q or None,
        content_status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/articles/{slug}/comments",
    response_model=AdminCommentsInResponse,
    name="admin:list-article-comments",
)
async def list_admin_article_comments(
    slug: str,
    q: str = "",
    status_filter: str = Query("all", alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    admin_repo: AdminRepository = Depends(get_repository(AdminRepository)),
) -> AdminCommentsInResponse:
    _validate_content_status(status_filter, allow_all=True)
    return await admin_repo.list_comments_for_article(
        slug=slug,
        q=q or None,
        content_status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    name="admin:delete-comment",
    response_class=Response,
)
async def delete_admin_comment(
    comment_id: int,
    user: User = Depends(get_admin_user),
    admin_repo: AdminRepository = Depends(get_repository(AdminRepository)),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> None:
    try:
        transition = await admin_repo.set_comment_status(
            comment_id=comment_id,
            content_status="hidden",
        )
    except EntityDoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=strings.COMMENT_DOES_NOT_EXIST,
        )
    await _record_transition(
        governance_repo=governance_repo,
        actor=user,
        transition=transition,
        action="manual_hide",
        note="",
    )


@router.put(
    "/comments/{comment_id}/status",
    status_code=status.HTTP_204_NO_CONTENT,
    name="admin:update-comment-status",
    response_class=Response,
)
async def update_admin_comment_status(
    comment_id: int,
    update: ContentStatusInUpdate = Body(...),
    user: User = Depends(get_admin_user),
    admin_repo: AdminRepository = Depends(get_repository(AdminRepository)),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> None:
    _validate_content_status(update.status)
    try:
        transition = await admin_repo.set_comment_status(
            comment_id=comment_id,
            content_status=update.status,
        )
    except EntityDoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=strings.COMMENT_DOES_NOT_EXIST,
        )
    await _record_transition(
        governance_repo=governance_repo,
        actor=user,
        transition=transition,
        action="manual_status_update",
        note=update.note,
    )


def _validate_content_status(status_value: str, *, allow_all: bool = False) -> None:
    allowed = {*CONTENT_STATUSES, "all"} if allow_all else CONTENT_STATUSES
    if status_value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported content status.",
        )


def _validate_review_status(status_value: str) -> None:
    if status_value not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported review status.",
        )


def _validate_review_action(action: str) -> None:
    if action not in REVIEW_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported review action.",
        )


def _validate_report_status(status_value: str) -> None:
    if status_value not in REPORT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported report status.",
        )


def _validate_report_type(content_type: str) -> None:
    if content_type not in REPORT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported content type.",
        )


def _validate_report_action(action: str) -> None:
    if action not in REPORT_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported report action.",
        )


async def _record_transition(
    *,
    governance_repo: GovernanceRepository,
    actor: User,
    transition: dict,
    action: str,
    note: str,
) -> None:
    await governance_repo.create_audit_log(
        content_type=transition["content_type"],
        article_id=transition["article_id"],
        comment_id=transition["comment_id"],
        actor=actor,
        action=action,
        from_status=transition["from_status"],
        to_status=transition["to_status"],
        note=note,
        metadata=transition.get("metadata"),
    )
    if not transition.get("author_id"):
        return
    await governance_repo.create_notification(
        user_id=transition["author_id"],
        notification_type=action,
        title=_notification_title(
            transition["content_type"],
            transition["to_status"],
            action,
        ),
        body=_notification_body(
            transition["content_type"],
            transition["to_status"],
            note,
            action,
        ),
        content_type=transition["content_type"],
        article_id=transition["article_id"],
        comment_id=transition["comment_id"],
    )


def _notification_title(content_type: str, to_status: str, action: str) -> str:
    if action.startswith("report_"):
        return "举报结果"
    subject = "文章" if content_type == "article" else "评论"
    if to_status == "visible":
        return "{0}审核已通过".format(subject)
    if to_status == "hidden":
        return "{0}审核未通过".format(subject)
    return "{0}状态已更新".format(subject)


def _notification_body(content_type: str, to_status: str, note: str, action: str) -> str:
    subject = "文章" if content_type == "article" else "评论"
    if action == "report_ignore":
        base = "管理员已驳回举报请求，{0}状态未变。".format(subject)
    elif action == "report_hide":
        base = "管理员已接受举报请求，{0}已设为不公开显示。".format(subject)
    elif to_status == "visible":
        base = "{0}已恢复显示。".format(subject)
    elif to_status == "hidden":
        base = "{0}当前不再公开显示。".format(subject)
    else:
        base = "{0}状态已更新为 {1}。".format(subject, to_status)
    if note:
        return "{0}处理备注：{1}".format(base, note)
    return base
