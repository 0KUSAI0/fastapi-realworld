from typing import List

from pydantic import BaseModel, Field, confloat, conint

from app.models.schemas.articles import (
    ArticleInCreate,
    ArticleSuggestionRevisionResult,
)
from app.services.ai.article_polish import _compute_diff
from app.services.ai.llm_client import ChatMessage, LLMClient

ARTICLE_REVISION_SYSTEM_PROMPT = """
You are an AI writing editor embedded in a blog drafting workflow.
The user selected one analysis suggestion. Revise the article to address only that suggestion.
Preserve the author's meaning, tone, title, description, and unrelated paragraphs.
Return only valid JSON with:
- revisedBody: the complete article body after the targeted revision.
- changedParagraphIndex: zero-based index of the paragraph you changed.
- rationale: concise Chinese explanation of why this change addresses the suggestion.
- changesSummary: 1 to 4 short Chinese descriptions of the concrete edits.
- confidence: number from 0 to 1.
""".strip()


class ArticleRevisionLLMResponse(BaseModel):
    revised_body: str = Field(..., alias="revisedBody")
    changed_paragraph_index: conint(ge=0) = Field(..., alias="changedParagraphIndex")
    rationale: str
    changes_summary: List[str] = Field(..., alias="changesSummary")
    confidence: confloat(ge=0, le=1)


class ArticleSuggestionRevisionService:
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    async def revise_for_suggestion(
        self,
        *,
        article: ArticleInCreate,
        suggestion: str,
    ) -> ArticleSuggestionRevisionResult:
        response = await self._llm_client.generate_json(
            messages=[
                ChatMessage(role="system", content=ARTICLE_REVISION_SYSTEM_PROMPT),
                ChatMessage(
                    role="user",
                    content=self._build_user_prompt(article=article, suggestion=suggestion),
                ),
            ],
            schema=ArticleRevisionLLMResponse,
        )
        revision = ArticleRevisionLLMResponse.parse_obj(response.dict(by_alias=True))
        return ArticleSuggestionRevisionResult(
            original=article.body,
            revised=revision.revised_body,
            diff=_compute_diff(article.body, revision.revised_body),
            suggestion=suggestion,
            changedParagraphIndex=revision.changed_paragraph_index,
            rationale=revision.rationale,
            changesSummary=revision.changes_summary,
            confidence=float(revision.confidence),
            model=self._llm_client.model_name,
        )

    def _build_user_prompt(self, *, article: ArticleInCreate, suggestion: str) -> str:
        return """
Selected suggestion:
{suggestion}

Article title:
{title}

Article description:
{description}

Existing tags:
{tags}

Numbered body paragraphs:
{paragraphs}

Full original body:
{body}
""".strip().format(
            suggestion=suggestion,
            title=article.title,
            description=article.description,
            tags=", ".join(article.tags),
            paragraphs=self._numbered_paragraphs(article.body),
            body=article.body,
        )

    def _numbered_paragraphs(self, body: str) -> str:
        paragraphs = [part.strip() for part in body.split("\n\n") if part.strip()]
        if not paragraphs:
            paragraphs = [body.strip()]
        return "\n".join(
            "{0}. {1}".format(index, paragraph)
            for index, paragraph in enumerate(paragraphs)
        )
