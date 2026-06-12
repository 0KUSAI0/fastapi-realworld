import re
from typing import List, Optional, Set

from pydantic import BaseModel, Field

from app.models.domain.users import User
from app.models.schemas.articles import (
    ArticleLibraryQAResult,
    RecommendedArticleForResponse,
)
from app.services.ai.article_recommendation import ArticleRecommendationService
from app.services.ai.llm_client import ChatMessage, LLMClient

ARTICLE_LIBRARY_QA_SYSTEM_PROMPT = """
You are an AI assistant for a blog article library.
Answer the user's question only from the provided retrieved articles.
If the articles do not contain enough evidence, say so clearly and suggest what to search next.
Return only valid JSON with:
- answer: concise Chinese answer, 2 to 5 sentences.
- citations: list of source slugs used in the answer.
- suggestedQueries: 1 to 3 short Chinese follow-up search questions.
""".strip()

_MAX_CONTEXT_CHARS = 900
_RETRIEVAL_POOL_SIZE = 16
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", re.UNICODE)
_QUERY_STOPWORDS = {
    "有没有",
    "关于",
    "文章",
    "内容",
    "相关",
    "哪些",
    "什么",
    "这个",
    "一个",
    "一篇",
    "可以",
    "一下",
}
_NOISE_KEYWORDS = {
    "测试文章",
    "测试",
    "test article",
    "placeholder",
    "lorem ipsum",
    "demo article",
}


class ArticleLibraryQALLMResponse(BaseModel):
    answer: str
    citations: List[str] = Field(default_factory=list)
    suggested_queries: List[str] = Field(default_factory=list, alias="suggestedQueries")


class ArticleLibraryQAService:
    def __init__(
        self,
        *,
        llm_client: LLMClient,
        recommendation_service: ArticleRecommendationService,
    ) -> None:
        self._llm_client = llm_client
        self._recommendation_service = recommendation_service

    async def answer_question(
        self,
        *,
        question: str,
        requested_user: Optional[User],
        limit: int,
    ) -> ArticleLibraryQAResult:
        retrieval_limit = max(limit, _RETRIEVAL_POOL_SIZE)
        sources = await self._recommendation_service.search_by_text(
            query=question,
            requested_user=requested_user,
            limit=retrieval_limit,
        )
        if not sources:
            return ArticleLibraryQAResult(
                question=question,
                answer="文章库里暂时没有找到足够相关的内容。可以换一个更具体的关键词再问。",
                sources=[],
                citations=[],
                suggestedQueries=[],
                model=self._llm_client.model_name,
            )

        sources = self._rerank_sources(question=question, sources=sources)[:limit]

        response = await self._llm_client.generate_json(
            messages=[
                ChatMessage(role="system", content=ARTICLE_LIBRARY_QA_SYSTEM_PROMPT),
                ChatMessage(
                    role="user",
                    content=self._build_user_prompt(question=question, sources=sources),
                ),
            ],
            schema=ArticleLibraryQALLMResponse,
        )
        answer = ArticleLibraryQALLMResponse.parse_obj(response.dict(by_alias=True))
        valid_slugs = [item.article.slug for item in sources]
        citations = [slug for slug in answer.citations if slug in valid_slugs]
        if not citations:
            citations = valid_slugs[: min(2, len(valid_slugs))]

        return ArticleLibraryQAResult(
            question=question,
            answer=answer.answer,
            sources=sources,
            citations=citations,
            suggestedQueries=answer.suggested_queries,
            model=self._llm_client.model_name,
        )

    def _build_user_prompt(
        self,
        *,
        question: str,
        sources: List[RecommendedArticleForResponse],
    ) -> str:
        source_blocks = "\n\n".join(
            self._source_block(index=index + 1, source=source)
            for index, source in enumerate(sources)
        )
        return """
Question:
{question}

Retrieved articles:
{source_blocks}
""".strip().format(question=question, source_blocks=source_blocks)

    def _source_block(self, *, index: int, source: RecommendedArticleForResponse) -> str:
        article = source.article
        body = article.body or ""
        excerpt = body[:_MAX_CONTEXT_CHARS]
        if len(body) > _MAX_CONTEXT_CHARS:
            excerpt = "{0}...".format(excerpt)
        return """
[{index}]
Slug: {slug}
Title: {title}
Description: {description}
Tags: {tags}
Search reason: {reason}
Excerpt:
{excerpt}
""".strip().format(
            index=index,
            slug=article.slug,
            title=article.title,
            description=article.description,
            tags=", ".join(article.tags),
            reason=source.reason,
            excerpt=excerpt,
        )

    def _rerank_sources(
        self,
        *,
        question: str,
        sources: List[RecommendedArticleForResponse],
    ) -> List[RecommendedArticleForResponse]:
        query_terms = self._query_terms(question)
        return sorted(
            sources,
            key=lambda source: self._source_score(source=source, query_terms=query_terms),
            reverse=True,
        )

    def _source_score(
        self,
        *,
        source: RecommendedArticleForResponse,
        query_terms: Set[str],
    ) -> float:
        article = source.article
        title = (article.title or "").lower()
        description = (article.description or "").lower()
        tags = " ".join(article.tags or []).lower()
        body = (article.body or "")[:_MAX_CONTEXT_CHARS].lower()
        combined = "\n".join([title, description, tags, body])

        score = float(source.similarity_score or 0) * 0.2
        for term in query_terms:
            if term in title:
                score += 4.0
            if term in tags:
                score += 3.0
            if term in description:
                score += 2.0
            if term in body:
                score += 1.0
        if any(keyword in combined for keyword in _NOISE_KEYWORDS):
            score -= 8.0
        return score

    def _query_terms(self, question: str) -> Set[str]:
        normalized = question.lower()
        terms: Set[str] = set()
        ascii_buffer: List[str] = []
        cjk_chars: List[str] = []
        for token in _TOKEN_RE.findall(normalized):
            if token.isascii():
                ascii_buffer.append(token)
            else:
                cjk_chars.append(token)

        terms.update(term for term in ascii_buffer if len(term) > 2)
        cjk_text = "".join(cjk_chars)
        for size in (2, 3, 4):
            for index in range(0, max(0, len(cjk_text) - size + 1)):
                term = cjk_text[index : index + size]
                if term not in _QUERY_STOPWORDS:
                    terms.add(term)

        return {term for term in terms if term and term not in _QUERY_STOPWORDS}
