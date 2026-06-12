from typing import List

from pydantic import BaseModel, Field, conint

from app.models.schemas.articles import ArticleAIAnalysis, ArticleInCreate
from app.services.ai.llm_client import ChatMessage, LLMClient

ARTICLE_ANALYSIS_SYSTEM_PROMPT = """
You are an AI writing assistant embedded in a RealWorld/Conduit blog backend.
Analyze article drafts for creators. Return only valid JSON.
The JSON object must contain:
- summary: concise Chinese summary, max 120 Chinese characters.
- recommendedTagList: 1 to 5 lowercase short tags.
- contentScore: integer from 0 to 100.
- riskLabels: array of short labels, empty if no risk.
- suggestions: 1 to 5 practical Chinese suggestions.
""".strip()


class ArticleAnalysisLLMResponse(BaseModel):
    summary: str
    recommended_tag_list: List[str] = Field(..., alias="recommendedTagList")
    content_score: conint(ge=0, le=100) = Field(..., alias="contentScore")
    risk_labels: List[str] = Field(default_factory=list, alias="riskLabels")
    suggestions: List[str]


class ArticleAssistantService:
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    async def analyze_article(self, article: ArticleInCreate) -> ArticleAIAnalysis:
        response = await self._llm_client.generate_json(
            messages=[
                ChatMessage(role="system", content=ARTICLE_ANALYSIS_SYSTEM_PROMPT),
                ChatMessage(role="user", content=self._build_user_prompt(article)),
            ],
            schema=ArticleAnalysisLLMResponse,
        )
        analysis = ArticleAnalysisLLMResponse.parse_obj(response.dict(by_alias=True))
        return ArticleAIAnalysis(
            summary=analysis.summary,
            recommendedTagList=analysis.recommended_tag_list,
            readingTimeMinutes=self._calculate_reading_time(article.body),
            contentScore=analysis.content_score,
            riskLabels=analysis.risk_labels,
            suggestions=analysis.suggestions,
            model=self._llm_client.model_name,
        )

    def _build_user_prompt(self, article: ArticleInCreate) -> str:
        return """
Title:
{title}

Description:
{description}

Existing tags:
{tags}

Body:
{body}
""".strip().format(
            title=article.title,
            description=article.description,
            tags=", ".join(article.tags),
            body=article.body,
        )

    def _calculate_reading_time(self, text: str) -> int:
        word_count = max(1, len(text.split()))
        return max(1, round(word_count / 220))
