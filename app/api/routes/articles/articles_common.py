from fastapi import APIRouter, Body, Depends, HTTPException, Query
from starlette import status

from app.api.dependencies.articles import get_article_by_slug_from_path
from app.api.dependencies.ai import (
    get_article_library_qa_service,
    get_article_recommendation_service,
)
from app.api.dependencies.authentication import get_current_user_authorizer
from app.api.dependencies.database import get_repository
from app.db.repositories.articles import ArticlesRepository
from app.models.domain.articles import Article
from app.models.domain.users import User
from app.models.schemas.articles import (
    DEFAULT_ARTICLES_LIMIT,
    DEFAULT_ARTICLES_OFFSET,
    ArticleForResponse,
    ArticleInResponse,
    ArticleLibraryQAInResponse,
    ListOfArticlesInResponse,
    RecommendedArticlesInResponse,
    SemanticArticleSearchInResponse,
)
from app.resources import strings
from app.services.ai.errors import AIServiceError

router = APIRouter()


@router.get(
    "/semantic-search",
    response_model=SemanticArticleSearchInResponse,
    name="articles:semantic-search-articles",
)
async def semantic_search_articles(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
    user: User = Depends(get_current_user_authorizer(required=False)),
    recommendation_service=Depends(get_article_recommendation_service),
) -> SemanticArticleSearchInResponse:
    try:
        articles = await recommendation_service.search_by_text(
            query=q,
            requested_user=user,
            limit=limit,
        )
    except AIServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI semantic search is unavailable: {0}".format(exc),
        ) from exc

    return SemanticArticleSearchInResponse(
        articles=articles,
        articles_count=len(articles),
    )


@router.post(
    "/ai/ask",
    response_model=ArticleLibraryQAInResponse,
    name="articles:ask-article-library",
)
async def ask_article_library(
    question: str = Body(..., embed=True, min_length=1),
    limit: int = Body(5, embed=True, ge=1, le=8),
    user: User = Depends(get_current_user_authorizer(required=False)),
    qa_service=Depends(get_article_library_qa_service),
) -> ArticleLibraryQAInResponse:
    try:
        result = await qa_service.answer_question(
            question=question,
            requested_user=user,
            limit=limit,
        )
    except AIServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI article library assistant is unavailable: {0}".format(exc),
        ) from exc

    return ArticleLibraryQAInResponse(result=result)


@router.get(
    "/feed",
    response_model=ListOfArticlesInResponse,
    name="articles:get-user-feed-articles",
)
async def get_articles_for_user_feed(
    limit: int = Query(DEFAULT_ARTICLES_LIMIT, ge=1),
    offset: int = Query(DEFAULT_ARTICLES_OFFSET, ge=0),
    user: User = Depends(get_current_user_authorizer()),
    articles_repo: ArticlesRepository = Depends(get_repository(ArticlesRepository)),
) -> ListOfArticlesInResponse:
    articles = await articles_repo.get_articles_for_user_feed(
        user=user,
        limit=limit,
        offset=offset,
    )
    articles_for_response = [
        ArticleForResponse(**article.dict()) for article in articles
    ]
    return ListOfArticlesInResponse(
        articles=articles_for_response,
        articles_count=len(articles),
    )


@router.get(
    "/{slug}/recommendations",
    response_model=RecommendedArticlesInResponse,
    name="articles:get-recommended-articles",
)
async def get_recommended_articles(
    limit: int = Query(5, ge=1, le=20),
    article: Article = Depends(get_article_by_slug_from_path),
    user: User = Depends(get_current_user_authorizer(required=False)),
    recommendation_service=Depends(get_article_recommendation_service),
) -> RecommendedArticlesInResponse:
    try:
        recommendations = await recommendation_service.get_recommendations(
            article=article,
            requested_user=user,
            limit=limit,
        )
    except AIServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI article recommendations are unavailable: {0}".format(exc),
        ) from exc

    return RecommendedArticlesInResponse(
        articles=recommendations,
        articles_count=len(recommendations),
    )


@router.post(
    "/{slug}/favorite",
    response_model=ArticleInResponse,
    name="articles:mark-article-favorite",
)
async def mark_article_as_favorite(
    article: Article = Depends(get_article_by_slug_from_path),
    user: User = Depends(get_current_user_authorizer()),
    articles_repo: ArticlesRepository = Depends(get_repository(ArticlesRepository)),
) -> ArticleInResponse:
    if not article.favorited:
        await articles_repo.add_article_into_favorites(article=article, user=user)

        return ArticleInResponse(
            article=ArticleForResponse.from_orm(
                article.copy(
                    update={
                        "favorited": True,
                        "favorites_count": article.favorites_count + 1,
                    },
                ),
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=strings.ARTICLE_IS_ALREADY_FAVORITED,
    )


@router.delete(
    "/{slug}/favorite",
    response_model=ArticleInResponse,
    name="articles:unmark-article-favorite",
)
async def remove_article_from_favorites(
    article: Article = Depends(get_article_by_slug_from_path),
    user: User = Depends(get_current_user_authorizer()),
    articles_repo: ArticlesRepository = Depends(get_repository(ArticlesRepository)),
) -> ArticleInResponse:
    if article.favorited:
        await articles_repo.remove_article_from_favorites(article=article, user=user)

        return ArticleInResponse(
            article=ArticleForResponse.from_orm(
                article.copy(
                    update={
                        "favorited": False,
                        "favorites_count": article.favorites_count - 1,
                    },
                ),
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=strings.ARTICLE_IS_NOT_FAVORITED,
    )
