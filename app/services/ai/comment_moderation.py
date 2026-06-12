from pydantic import BaseModel, Field, confloat

from app.core.settings.app import AppSettings, CommentModerationMode
from app.models.domain.articles import Article
from app.models.domain.users import User
from app.models.schemas.comments import CommentModeration
from app.services.ai.llm_client import ChatMessage, LLMClient

COMMENT_MODERATION_SYSTEM_PROMPT = """
You are an AI content moderation assistant for a blog platform.
Classify the submitted comment. Return only valid JSON.
The JSON object must contain:
- allowed: boolean.
- category: one of safe, spam, toxic, harassment, hate, sexual, violence, self_harm, irrelevant, other.
- severity: one of low, medium, high.
- reason: concise Chinese reason.
- suggestedRevision: Chinese suggested rewrite, empty string if not needed.
- confidence: number from 0 to 1.
""".strip()


class CommentModerationLLMResponse(BaseModel):
    allowed: bool
    category: str
    severity: str
    reason: str
    suggested_revision: str = Field("", alias="suggestedRevision")
    confidence: confloat(ge=0, le=1)


class CommentModerationService:
    def __init__(self, llm_client: LLMClient, settings: AppSettings) -> None:
        self._llm_client = llm_client
        self._settings = settings

    @property
    def enabled_for_comment_creation(self) -> bool:
        return self._settings.ai_comment_moderation_mode != CommentModerationMode.off

    @property
    def should_block_rejected_comments(self) -> bool:
        return self._settings.ai_comment_moderation_mode == CommentModerationMode.block

    async def moderate_comment(
        self,
        *,
        article: Article,
        user: User,
        body: str,
    ) -> CommentModeration:
        response = await self._llm_client.generate_json(
            messages=[
                ChatMessage(role="system", content=COMMENT_MODERATION_SYSTEM_PROMPT),
                ChatMessage(
                    role="user",
                    content=self._build_user_prompt(article=article, user=user, body=body),
                ),
            ],
            schema=CommentModerationLLMResponse,
        )
        moderation = CommentModerationLLMResponse.parse_obj(response.dict(by_alias=True))
        return CommentModeration(
            allowed=moderation.allowed,
            category=moderation.category,
            severity=moderation.severity,
            reason=moderation.reason,
            suggestedRevision=moderation.suggested_revision,
            confidence=moderation.confidence,
            model=self._llm_client.model_name,
        )

    def _build_user_prompt(self, *, article: Article, user: User, body: str) -> str:
        return """
Article title:
{title}

Article description:
{description}

Comment author:
{username}

Comment:
{body}
""".strip().format(
            title=article.title,
            description=article.description,
            username=user.username,
            body=body,
        )


class DisabledCommentModerationService(CommentModerationService):
    @property
    def enabled_for_comment_creation(self) -> bool:
        return False

    async def moderate_comment(
        self,
        *,
        article: Article,
        user: User,
        body: str,
    ) -> CommentModeration:
        return CommentModeration(
            allowed=True,
            category="safe",
            severity="low",
            reason="AI moderation is disabled.",
            suggestedRevision="",
            confidence=1,
            model="disabled",
        )
