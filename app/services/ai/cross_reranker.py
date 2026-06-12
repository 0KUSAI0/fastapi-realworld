import asyncio
from typing import List, Optional

from pydantic import BaseModel, confloat

from app.models.domain.articles import Article
from app.services.ai.errors import AIServiceError
from app.services.ai.llm_client import ChatMessage, LLMClient

CROSS_RANKER_SYSTEM_PROMPT = """
You are a relevance scoring expert for a blog recommendation system.
Given a source article and a candidate article, evaluate how relevant and useful the candidate is for a reader who just finished the source article.
Return only valid JSON with:
- relevance_score: float from 0.0 to 1.0 (0=completely unrelated, 1=highly complementary or deeply relevant)
- reason: one or two sentences in Chinese explaining the relevance
""".strip()

EMBEDDING_WEIGHT = 0.35
LLM_WEIGHT = 0.65
_CONCURRENT_CALLS = 3


class CrossRankLLMResponse(BaseModel):
    relevance_score: confloat(ge=0.0, le=1.0)  # type: ignore[valid-type]
    reason: str


class CrossReranker:
    """LLM-based cross-encoder: scores source-candidate pairs for reranking.

    The caller is responsible for combining the LLM score with the embedding
    score using EMBEDDING_WEIGHT / LLM_WEIGHT from this module.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    @property
    def model_name(self) -> str:
        return self._llm_client.model_name

    async def score_pair(
        self,
        source: Article,
        candidate: Article,
    ) -> CrossRankLLMResponse:
        response = await self._llm_client.generate_json(
            messages=[
                ChatMessage(role="system", content=CROSS_RANKER_SYSTEM_PROMPT),
                ChatMessage(
                    role="user",
                    content=self._build_prompt(source, candidate),
                ),
            ],
            schema=CrossRankLLMResponse,
        )
        return CrossRankLLMResponse.parse_obj(response.dict())

    async def score_pairs(  # noqa: WPS210
        self,
        source: Article,
        candidates: List[Article],
    ) -> List[Optional[CrossRankLLMResponse]]:
        """Score candidates concurrently with a bounded semaphore.

        Returns None for any candidate whose LLM call fails, allowing the
        caller to fall back to the embedding score for that slot.
        """
        semaphore = asyncio.Semaphore(_CONCURRENT_CALLS)

        async def _safe_score(
            candidate: Article,
        ) -> Optional[CrossRankLLMResponse]:
            try:
                async with semaphore:
                    return await self.score_pair(source, candidate)
            except AIServiceError:
                return None

        tasks = [_safe_score(c) for c in candidates]
        return list(await asyncio.gather(*tasks))

    def _build_prompt(self, source: Article, candidate: Article) -> str:
        return (
            "Source article:\n"
            "Title: {source_title}\n"
            "Description: {source_desc}\n"
            "Tags: {source_tags}\n\n"
            "Candidate article:\n"
            "Title: {candidate_title}\n"
            "Description: {candidate_desc}\n"
            "Tags: {candidate_tags}"
        ).format(
            source_title=source.title,
            source_desc=source.description,
            source_tags=", ".join(source.tags),
            candidate_title=candidate.title,
            candidate_desc=candidate.description,
            candidate_tags=", ".join(candidate.tags),
        )
