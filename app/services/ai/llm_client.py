import json
from typing import List, Optional, Type

from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from app.core.settings.app import AppSettings
from app.services.ai.errors import AIResponseFormatError, AIServiceError

JSON_REPAIR_MESSAGE = (
    "Your previous answer was not valid JSON for the requested schema. "
    "Return only a JSON object. Do not include markdown fences or commentary."
)


class ChatMessage(BaseModel):
    role: str
    content: str


class LLMClient:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value() or "EMPTY",
            timeout=settings.llm_timeout_seconds,
        )

    async def generate_json(
        self,
        *,
        messages: List[ChatMessage],
        schema: Type[BaseModel],
    ) -> BaseModel:
        first_answer = await self._chat(messages=messages)
        parsed = self._parse_json(first_answer, schema=schema)
        if parsed is not None:
            return parsed

        repair_messages = [
            *messages,
            ChatMessage(role="assistant", content=first_answer),
            ChatMessage(role="user", content=JSON_REPAIR_MESSAGE),
        ]
        second_answer = await self._chat(messages=repair_messages)
        parsed = self._parse_json(second_answer, schema=schema)
        if parsed is None:
            raise AIResponseFormatError("model returned invalid JSON")

        return parsed

    @property
    def model_name(self) -> str:
        return self._settings.llm_model

    async def aclose(self) -> None:
        await self._client.close()

    async def _chat(self, *, messages: List[ChatMessage]) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._settings.llm_model,
                messages=[message.dict() for message in messages],
                temperature=0,
            )
        except OpenAIError as exc:
            raise AIServiceError("vLLM chat completion failed") from exc

        content = response.choices[0].message.content
        return content or ""

    def _parse_json(
        self,
        content: str,
        *,
        schema: Type[BaseModel],
    ) -> Optional[BaseModel]:
        try:
            return schema.parse_obj(json.loads(self._extract_json(content)))
        except (json.JSONDecodeError, ValidationError, ValueError):
            return None

    def _extract_json(self, content: str) -> str:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first == -1 or last == -1:
            raise ValueError("json object not found")

        return cleaned[first : last + 1]


def get_llm_client(settings: AppSettings) -> LLMClient:
    return LLMClient(settings)
