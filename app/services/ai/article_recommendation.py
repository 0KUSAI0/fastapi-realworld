import hashlib
from typing import Dict, List, Optional, Set, Tuple

from app.db.repositories.articles import ArticlesRepository
from app.models.domain.articles import Article
from app.models.domain.users import User
from app.models.schemas.articles import ArticleForResponse, RecommendedArticleForResponse
from app.services.ai.cross_reranker import (
    EMBEDDING_WEIGHT,
    LLM_WEIGHT,
    CrossReranker,
)
from app.services.ai.embedding_client import EmbeddingClient

_RERANK_POOL = 4


class ArticleRecommendationService:
    def __init__(
        self,
        *,
        embedding_client: EmbeddingClient,
        articles_repo: ArticlesRepository,
        cross_reranker: Optional[CrossReranker] = None,
    ) -> None:
        self._embedding_client = embedding_client
        self._articles_repo = articles_repo
        self._cross_reranker = cross_reranker

    async def get_recommendations(
        self,
        *,
        article: Article,
        requested_user: Optional[User],
        limit: int,
    ) -> List[RecommendedArticleForResponse]:
        await self._ensure_embeddings_for_recent_articles(
            requested_user=requested_user,
        )
        candidate_limit = max(limit * _RERANK_POOL, 20)
        rows = await self._articles_repo.get_recommended_articles(
            slug=article.slug,
            limit=candidate_limit,
            requested_user=requested_user,
        )
        preference_profile = await self._favorite_preference_profile(requested_user)

        if self._cross_reranker is not None and rows:
            reranked = await self._cross_rerank_with_cache(article, rows, top_k=limit)
            return [
                RecommendedArticleForResponse(
                    article=ArticleForResponse.from_orm(rec),
                    similarityScore=score,
                    reason=reason or self._recommendation_reason(
                        article, rec, score, preference_profile,
                    ),
                )
                for rec, score, reason in reranked
            ]

        return [
            RecommendedArticleForResponse(
                article=ArticleForResponse.from_orm(rec),
                similarityScore=score,
                reason=self._recommendation_reason(
                    article, rec, score, preference_profile,
                ),
            )
            for rec, score in rows[:limit]
        ]

    async def search_by_text(
        self,
        *,
        query: str,
        requested_user: Optional[User],
        limit: int,
    ) -> List[RecommendedArticleForResponse]:
        await self._ensure_embeddings_for_recent_articles(
            requested_user=requested_user,
        )
        query_embedding = await self._embedding_client.embed_text(query)
        rows = await self._articles_repo.search_articles_by_embedding(
            embedding=query_embedding,
            limit=limit,
            requested_user=requested_user,
        )
        return [
            RecommendedArticleForResponse(
                article=ArticleForResponse.from_orm(article),
                similarityScore=similarity_score,
                reason=self._search_reason(query, article, similarity_score),
            )
            for article, similarity_score in rows
        ]

    async def _cross_rerank_with_cache(  # noqa: WPS210
        self,
        source: Article,
        candidates: List[Tuple[Article, float]],
        top_k: int,
    ) -> List[Tuple[Article, float, str]]:
        assert self._cross_reranker is not None

        cache: Dict[int, Tuple[float, str]] = {}
        uncached_indices: List[int] = []

        for idx, (candidate, _) in enumerate(candidates):
            cached = await self._articles_repo.get_recommendation_reason_cache(
                source_article_id=source.id_,
                target_article_id=candidate.id_,
                model_name=self._cross_reranker.model_name,
            )
            if cached is not None:
                cache[idx] = cached
            else:
                uncached_indices.append(idx)

        if uncached_indices:
            uncached_articles = [candidates[i][0] for i in uncached_indices]
            llm_results = await self._cross_reranker.score_pairs(
                source, uncached_articles,
            )
            for list_pos, idx in enumerate(uncached_indices):
                result = llm_results[list_pos]
                if result is not None:
                    await self._articles_repo.upsert_recommendation_reason_cache(
                        source_article_id=source.id_,
                        target_article_id=candidates[idx][0].id_,
                        model_name=self._cross_reranker.model_name,
                        relevance_score=result.relevance_score,
                        reason=result.reason,
                    )
                    cache[idx] = (float(result.relevance_score), result.reason)

        scored: List[Tuple[Article, float, str]] = []
        for idx, (candidate, embedding_score) in enumerate(candidates):
            if idx in cache:
                llm_score, reason = cache[idx]
                combined = EMBEDDING_WEIGHT * embedding_score + LLM_WEIGHT * llm_score
            else:
                combined = embedding_score
                reason = ""
            scored.append((candidate, combined, reason))

        return sorted(scored, key=lambda row: row[1], reverse=True)[:top_k]

    async def _ensure_embeddings_for_recent_articles(
        self,
        *,
        requested_user: Optional[User],
    ) -> None:
        articles = await self._articles_repo.filter_articles(
            limit=100,
            offset=0,
            requested_user=requested_user,
        )
        for article in articles:
            await self.ensure_embedding(article)

    async def ensure_embedding(self, article: Article) -> None:
        text = self._article_text(article)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        is_fresh = await self._articles_repo.is_article_embedding_fresh(
            article=article,
            model_name=self._embedding_client.model_name,
            content_hash=content_hash,
        )
        if is_fresh:
            return

        embedding = await self._embedding_client.embed_text(text)
        await self._articles_repo.upsert_article_embedding(
            article=article,
            model_name=self._embedding_client.model_name,
            content_hash=content_hash,
            embedding=embedding,
        )

    def _article_text(self, article: Article) -> str:
        return "\n".join(
            [
                article.title,
                article.description,
                ", ".join(article.tags),
                article.body,
            ],
        )

    def _recommendation_reason(  # noqa: WPS211
        self,
        source_article: Article,
        target_article: Article,
        similarity_score: float,
        preference_profile: Optional[Dict[str, Set[str]]],
    ) -> str:
        if preference_profile:
            favorite_tags = preference_profile["tags"]
            favorite_authors = preference_profile["authors"]
            overlap_with_favorites = [
                tag for tag in target_article.tags if tag in favorite_tags
            ]
            if overlap_with_favorites:
                return "你收藏过相似主题：{0}".format(
                    "、".join(overlap_with_favorites[:3]),
                )
            if target_article.author.username in favorite_authors:
                return "来自你收藏过的作者"
        shared_tags = [
            tag for tag in target_article.tags if tag in set(source_article.tags)
        ]
        if shared_tags:
            return "同主题标签：{0}".format("、".join(shared_tags[:3]))
        if similarity_score >= 0.75:
            return "正文语义接近，主题相关度较高"
        if target_article.author.username == source_article.author.username:
            return "同一作者的相关文章"
        return "与当前文章内容相近"

    def _search_reason(
        self,
        query: str,
        article: Article,
        similarity_score: float,
    ) -> str:
        lowered_query = query.lower()
        matched_tags = [
            tag for tag in article.tags if lowered_query in tag.lower()
        ]
        if matched_tags:
            return "命中标签：{0}".format("、".join(matched_tags[:3]))
        if lowered_query in article.title.lower():
            return "标题与搜索词高度相关"
        if lowered_query in article.description.lower():
            return "摘要与搜索词高度相关"
        if similarity_score >= 0.75:
            return "正文语义与搜索意图接近"
        return "与搜索主题相关"

    async def _favorite_preference_profile(
        self,
        requested_user: Optional[User],
    ) -> Optional[Dict[str, Set[str]]]:
        if requested_user is None:
            return None
        favorite_articles = await self._articles_repo.filter_articles(
            favorited=requested_user.username,
            limit=50,
            offset=0,
            requested_user=requested_user,
        )
        if not favorite_articles:
            return None
        return {
            "tags": {
                tag
                for favorite_article in favorite_articles
                for tag in favorite_article.tags
            },
            "authors": {
                favorite_article.author.username for favorite_article in favorite_articles
            },
        }
