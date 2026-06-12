from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.domain.articles import Article
from app.models.schemas.rwschema import RWSchema


class SentenceDiff(RWSchema):
    op: str
    text: str


class ArticlePolishResult(RWSchema):
    original: str
    polished: str
    diff: List[SentenceDiff]
    critique: str
    changes_summary: List[str]
    improvement_score: float
    iterations: int
    model: str


class ArticlePolishInResponse(RWSchema):
    result: ArticlePolishResult


class ArticleSuggestionRevisionResult(RWSchema):
    original: str
    revised: str
    diff: List[SentenceDiff]
    suggestion: str
    changed_paragraph_index: int = Field(..., alias="changedParagraphIndex")
    rationale: str
    changes_summary: List[str]
    confidence: float
    model: str


class ArticleSuggestionRevisionInResponse(RWSchema):
    result: ArticleSuggestionRevisionResult


DEFAULT_ARTICLES_LIMIT = 20
DEFAULT_ARTICLES_OFFSET = 0


class ArticleForResponse(RWSchema, Article):
    tags: List[str] = Field(..., alias="tagList")


class ArticleInResponse(RWSchema):
    article: ArticleForResponse


class ArticleInCreate(RWSchema):
    title: str
    description: str
    body: str
    tags: List[str] = Field([], alias="tagList")


class ArticleAIAnalysis(RWSchema):
    summary: str
    recommended_tags: List[str] = Field(..., alias="recommendedTagList")
    reading_time_minutes: int
    content_score: int
    risk_labels: List[str] = Field([], alias="riskLabels")
    suggestions: List[str]
    model: str = ""


class RecommendedArticleForResponse(RWSchema):
    article: ArticleForResponse
    similarity_score: float
    reason: str = ""


class RecommendedArticlesInResponse(RWSchema):
    articles: List[RecommendedArticleForResponse]
    articles_count: int


class SemanticArticleSearchInResponse(RWSchema):
    articles: List[RecommendedArticleForResponse]
    articles_count: int


class ArticleLibraryQAResult(RWSchema):
    question: str
    answer: str
    sources: List[RecommendedArticleForResponse]
    citations: List[str]
    suggested_queries: List[str]
    model: str


class ArticleLibraryQAInResponse(RWSchema):
    result: ArticleLibraryQAResult


class ArticleAIAnalysisInResponse(RWSchema):
    analysis: ArticleAIAnalysis


class ArticleInUpdate(RWSchema):
    title: Optional[str] = None
    description: Optional[str] = None
    body: Optional[str] = None
    tags: Optional[List[str]] = Field(None, alias="tagList")
    submit_for_review: bool = Field(False, alias="submitForReview")


class ListOfArticlesInResponse(RWSchema):
    articles: List[ArticleForResponse]
    articles_count: int


class ArticlesFilters(BaseModel):
    tag: Optional[str] = None
    q: Optional[str] = None
    author: Optional[str] = None
    favorited: Optional[str] = None
    limit: int = Field(DEFAULT_ARTICLES_LIMIT, ge=1)
    offset: int = Field(DEFAULT_ARTICLES_OFFSET, ge=0)
