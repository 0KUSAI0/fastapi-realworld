from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from starlette import status

from app.core.config import get_app_settings
from app.core.settings.app import AppSettings
from app.api.dependencies.articles import (
    check_article_modification_permissions,
    get_article_by_slug_for_author_from_path,
    get_article_by_slug_from_path,
    get_articles_filters,
)
from app.api.dependencies.ai import (
    get_article_assistant_service,
    get_article_polish_service,
    get_article_suggestion_revision_service,
)
from app.api.dependencies.authentication import get_current_user_authorizer
from app.api.dependencies.database import get_repository
from app.db.repositories.articles import ArticlesRepository
from app.db.repositories.governance import GovernanceRepository
from app.models.domain.articles import Article
from app.models.domain.users import User
from app.models.schemas.articles import (
    ArticleAIAnalysisInResponse,
    ArticleForResponse,
    ArticleInCreate,
    ArticleInResponse,
    ArticleInUpdate,
    ArticlePolishInResponse,
    ArticleSuggestionRevisionInResponse,
    ArticlesFilters,
    ListOfArticlesInResponse,
)
from app.models.schemas.governance import (
    ContentReportInCreate,
    ContentReportInResponse,
)
from app.resources import strings
from app.services.ai.article_assistant import ArticleAssistantService
from app.services.ai.article_polish import ArticlePolishService
from app.services.ai.article_revision import ArticleSuggestionRevisionService
from app.services.ai.errors import AIServiceError
from app.services.articles import check_article_exists, get_slug_for_article

router = APIRouter()


@router.post(
    "/ai/analyze",
    response_model=ArticleAIAnalysisInResponse,
    name="articles:analyze-article-with-ai",
)
async def analyze_article_with_ai(
    article_create: ArticleInCreate = Body(..., embed=True, alias="article"),
    user: User = Depends(get_current_user_authorizer()),
    article_assistant: ArticleAssistantService = Depends(
        get_article_assistant_service,
    ),
) -> ArticleAIAnalysisInResponse:
    try:
        analysis = await article_assistant.analyze_article(article_create)
    except AIServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI article analysis is unavailable: {0}".format(exc),
        ) from exc

    return ArticleAIAnalysisInResponse(analysis=analysis)


@router.post(
    "/ai/polish",
    response_model=ArticlePolishInResponse,
    name="articles:polish-article-section",
)
async def polish_article_section(
    body: str = Body(..., embed=True),
    instruction: str = Body(..., embed=True),
    user: User = Depends(get_current_user_authorizer()),
    polish_service: ArticlePolishService = Depends(get_article_polish_service),
) -> ArticlePolishInResponse:
    try:
        result = await polish_service.polish(text=body, instruction=instruction)
    except AIServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI polish service is unavailable: {0}".format(exc),
        ) from exc

    return ArticlePolishInResponse(result=result)


@router.post(
    "/ai/revise-suggestion",
    response_model=ArticleSuggestionRevisionInResponse,
    name="articles:revise-article-suggestion",
)
async def revise_article_suggestion(
    article_create: ArticleInCreate = Body(..., embed=True, alias="article"),
    suggestion: str = Body(..., embed=True),
    user: User = Depends(get_current_user_authorizer()),
    revision_service: ArticleSuggestionRevisionService = Depends(
        get_article_suggestion_revision_service,
    ),
) -> ArticleSuggestionRevisionInResponse:
    try:
        result = await revision_service.revise_for_suggestion(
            article=article_create,
            suggestion=suggestion,
        )
    except AIServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI article revision is unavailable: {0}".format(exc),
        ) from exc

    return ArticleSuggestionRevisionInResponse(result=result)


@router.get("", response_model=ListOfArticlesInResponse, name="articles:list-articles")
async def list_articles(
    articles_filters: ArticlesFilters = Depends(get_articles_filters),
    user: Optional[User] = Depends(get_current_user_authorizer(required=False)),
    articles_repo: ArticlesRepository = Depends(get_repository(ArticlesRepository)),
) -> ListOfArticlesInResponse:
    articles = await articles_repo.filter_articles(
        tag=articles_filters.tag,
        q=articles_filters.q,
        author=articles_filters.author,
        favorited=articles_filters.favorited,
        limit=articles_filters.limit,
        offset=articles_filters.offset,
        requested_user=user,
    )
    articles_for_response = [
        ArticleForResponse.from_orm(article) for article in articles
    ]
    return ListOfArticlesInResponse(
        articles=articles_for_response,
        articles_count=len(articles),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ArticleInResponse,
    name="articles:create-article",
)
async def create_new_article(
    article_create: ArticleInCreate = Body(..., embed=True, alias="article"),
    user: User = Depends(get_current_user_authorizer()),
    articles_repo: ArticlesRepository = Depends(get_repository(ArticlesRepository)),
    article_assistant: ArticleAssistantService = Depends(
        get_article_assistant_service,
    ),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
    settings: AppSettings = Depends(get_app_settings),
) -> ArticleInResponse:
    slug = get_slug_for_article(article_create.title)
    if await check_article_exists(articles_repo, slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=strings.ARTICLE_ALREADY_EXISTS,
        )

    analysis = None
    content_status = "visible"
    if settings.ai_article_review_on_publish:
        try:
            analysis = await article_assistant.analyze_article(article_create)
        except AIServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI article review is unavailable: {0}".format(exc),
            ) from exc

        if (
            analysis.content_score < settings.ai_article_min_content_score
            or analysis.risk_labels
        ):
            content_status = "pending"

    article = await articles_repo.create_article(
        slug=slug,
        title=article_create.title,
        description=article_create.description,
        body=article_create.body,
        author=user,
        tags=article_create.tags,
        content_status=content_status,
    )
    if analysis:
        await articles_repo.create_moderation_log(
            article=article,
            analysis=analysis,
            allowed=content_status == "visible",
            review_status="approved" if content_status == "visible" else "pending",
        )
        if content_status == "pending":
            await governance_repo.create_audit_log(
                content_type="article",
                article_id=article.id_,
                action="ai_pending_review",
                from_status="draft",
                to_status="pending",
                note="AI review marked this article for manual review.",
                metadata={"riskLabels": analysis.risk_labels},
            )
            await governance_repo.create_notification(
                user_id=user.id_,
                notification_type="article_pending_review",
                title="文章已进入待审核",
                body="AI 初审认为文章需要人工复核，通过后会公开显示。",
                content_type="article",
                article_id=article.id_,
            )
    return ArticleInResponse(article=ArticleForResponse.from_orm(article))


@router.post(
    "/{slug}/report",
    response_model=ContentReportInResponse,
    name="articles:report-article",
)
async def report_article(
    report: ContentReportInCreate = Body(..., embed=True, alias="report"),
    article: Article = Depends(get_article_by_slug_from_path),
    user: User = Depends(get_current_user_authorizer()),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> ContentReportInResponse:
    return await governance_repo.create_article_report(
        article=article,
        reporter=user,
        reason=report.reason,
        detail=report.detail,
    )


@router.get("/{slug}", response_model=ArticleInResponse, name="articles:get-article")
async def retrieve_article_by_slug(
    article: Article = Depends(get_article_by_slug_from_path),
) -> ArticleInResponse:
    return ArticleInResponse(article=ArticleForResponse.from_orm(article))


@router.put(
    "/{slug}",
    response_model=ArticleInResponse,
    name="articles:update-article",
    dependencies=[Depends(check_article_modification_permissions)],
)
async def update_article_by_slug(
    article_update: ArticleInUpdate = Body(..., embed=True, alias="article"),
    current_article: Article = Depends(get_article_by_slug_for_author_from_path),
    articles_repo: ArticlesRepository = Depends(get_repository(ArticlesRepository)),
    article_assistant: ArticleAssistantService = Depends(
        get_article_assistant_service,
    ),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
    settings: AppSettings = Depends(get_app_settings),
) -> ArticleInResponse:
    slug = get_slug_for_article(article_update.title) if article_update.title else None
    article = await articles_repo.update_article(
        article=current_article,
        slug=slug,
        **article_update.dict(exclude={"submit_for_review"}),
    )
    if article_update.submit_for_review:
        await articles_repo.set_article_content_status(
            slug=article.slug,
            status="pending",
        )
        article.content_status = "pending"
        if settings.ai_article_review_on_publish:
            article_create = ArticleInCreate(
                title=article.title,
                description=article.description,
                body=article.body,
                tagList=article.tags,
            )
            analysis = await article_assistant.analyze_article(article_create)
            await articles_repo.create_moderation_log(
                article=article,
                analysis=analysis,
                allowed=False,
                review_status="pending",
            )
            await governance_repo.create_audit_log(
                content_type="article",
                article_id=article.id_,
                action="author_resubmit",
                from_status=current_article.content_status,
                to_status="pending",
                note="作者已修改并重新提交文章审核。",
                metadata={"riskLabels": analysis.risk_labels},
            )
        else:
            await governance_repo.create_audit_log(
                content_type="article",
                article_id=article.id_,
                action="author_resubmit",
                from_status=current_article.content_status,
                to_status="pending",
                note="作者已修改并重新提交文章审核。",
            )
    return ArticleInResponse(article=ArticleForResponse.from_orm(article))


@router.delete(
    "/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    name="articles:delete-article",
    dependencies=[Depends(check_article_modification_permissions)],
    response_class=Response,
)
async def delete_article_by_slug(
    article: Article = Depends(get_article_by_slug_from_path),
    articles_repo: ArticlesRepository = Depends(get_repository(ArticlesRepository)),
) -> None:
    await articles_repo.delete_article(article=article)
