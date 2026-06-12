import re
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

from pydantic import BaseModel, confloat

from app.models.schemas.articles import ArticlePolishResult, SentenceDiff
from app.services.ai.llm_client import ChatMessage, LLMClient

_SENTENCE_END = re.compile(r"(?<=[。！？])|(?<=[.!?])\s+|\n{2,}")
_MAX_ITERATIONS = 2
_IMPROVEMENT_THRESHOLD = 0.65

_CRITIQUE_SYSTEM = """
You are a professional writing critic. Analyze the given text strictly against the user's rewrite instruction.
Return only valid JSON with:
- issues: list of 2-5 specific problems found (strings)
- overall_assessment: one-sentence Chinese overview of the main weakness
""".strip()

_REVISION_SYSTEM = """
You are a skilled writing editor. Rewrite the text to address every issue in the critique.
Preserve the author's meaning and topic. Do NOT introduce new content.
Return only valid JSON with:
- polished_text: the complete rewritten text (string)
- changes_made: list of short Chinese descriptions of each change applied (strings)
""".strip()

_VERIFICATION_SYSTEM = """
You are a writing quality assessor. Check whether the revision resolves the original critique issues.
Return only valid JSON with:
- improvement_score: float 0.0-1.0 (0=no improvement, 1=all issues fully resolved)
- addressed_issues: list of issues that were fixed (strings)
- remaining_issues: list of issues still present (strings)
- feedback: one-sentence Chinese suggestion for further improvement, or empty string
""".strip()


class _CritiqueOutput(BaseModel):
    issues: List[str]
    overall_assessment: str


class _RevisionOutput(BaseModel):
    polished_text: str
    changes_made: List[str]


class _VerificationOutput(BaseModel):
    improvement_score: confloat(ge=0.0, le=1.0)  # type: ignore[valid-type]
    addressed_issues: List[str]
    remaining_issues: List[str]
    feedback: str


class ArticlePolishService:
    """Three-stage Critique → Revise → Verify pipeline for article polishing.

    Runs up to _MAX_ITERATIONS refinement rounds. Stops early when the
    Verifier scores the revision above _IMPROVEMENT_THRESHOLD. If the
    second iteration does not improve on the first, the best-scoring
    revision is returned.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    async def polish(self, *, text: str, instruction: str) -> ArticlePolishResult:  # noqa: WPS210
        critique = await self._critique(text, instruction)

        current_text = text
        best: Optional[Tuple[str, _VerificationOutput, List[str]]] = None
        final_iteration = 1

        for iteration in range(1, _MAX_ITERATIONS + 1):
            revision = await self._revise(current_text, instruction, critique)
            verification = await self._verify(text, revision.polished_text, critique)
            final_iteration = iteration

            if best is None or verification.improvement_score > best[1].improvement_score:
                best = (revision.polished_text, verification, revision.changes_made)

            if verification.improvement_score >= _IMPROVEMENT_THRESHOLD:
                break

            remaining = list(verification.remaining_issues)
            if verification.feedback:
                remaining.append(verification.feedback)
            critique = _CritiqueOutput(
                issues=remaining or critique.issues,
                overall_assessment=verification.feedback or critique.overall_assessment,
            )
            current_text = revision.polished_text

        polished_text, verification, changes_made = best  # type: ignore[misc]
        return ArticlePolishResult(
            original=text,
            polished=polished_text,
            diff=_compute_diff(text, polished_text),
            critique=critique.overall_assessment,
            changes_summary=changes_made,
            improvement_score=float(verification.improvement_score),
            iterations=final_iteration,
            model=self._llm_client.model_name,
        )

    async def _critique(self, text: str, instruction: str) -> _CritiqueOutput:
        response = await self._llm_client.generate_json(
            messages=[
                ChatMessage(role="system", content=_CRITIQUE_SYSTEM),
                ChatMessage(
                    role="user",
                    content="Instruction: {0}\n\nText:\n{1}".format(instruction, text),
                ),
            ],
            schema=_CritiqueOutput,
        )
        return _CritiqueOutput.parse_obj(response.dict())

    async def _revise(  # noqa: WPS211
        self,
        text: str,
        instruction: str,
        critique: _CritiqueOutput,
    ) -> _RevisionOutput:
        issues_block = "\n".join("- {0}".format(issue) for issue in critique.issues)
        user_msg = (
            "Instruction: {instruction}\n\n"
            "Original text:\n{text}\n\n"
            "Critique assessment: {assessment}\n"
            "Issues to fix:\n{issues}"
        ).format(
            instruction=instruction,
            text=text,
            assessment=critique.overall_assessment,
            issues=issues_block,
        )
        response = await self._llm_client.generate_json(
            messages=[
                ChatMessage(role="system", content=_REVISION_SYSTEM),
                ChatMessage(role="user", content=user_msg),
            ],
            schema=_RevisionOutput,
        )
        return _RevisionOutput.parse_obj(response.dict())

    async def _verify(
        self,
        original: str,
        revised: str,
        critique: _CritiqueOutput,
    ) -> _VerificationOutput:
        issues_block = "\n".join("- {0}".format(issue) for issue in critique.issues)
        user_msg = (
            "Original text:\n{original}\n\n"
            "Critique issues:\n{issues}\n\n"
            "Revised text:\n{revised}"
        ).format(original=original, issues=issues_block, revised=revised)
        response = await self._llm_client.generate_json(
            messages=[
                ChatMessage(role="system", content=_VERIFICATION_SYSTEM),
                ChatMessage(role="user", content=user_msg),
            ],
            schema=_VerificationOutput,
        )
        return _VerificationOutput.parse_obj(response.dict())


def _compute_diff(original: str, polished: str) -> List[SentenceDiff]:
    orig_sents = _split_sentences(original)
    new_sents = _split_sentences(polished)
    matcher = SequenceMatcher(None, orig_sents, new_sents, autojunk=False)
    result: List[SentenceDiff] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            result.extend(SentenceDiff(op="keep", text=s) for s in orig_sents[i1:i2])
        elif tag in ("replace", "delete"):
            result.extend(SentenceDiff(op="delete", text=s) for s in orig_sents[i1:i2])
            if tag == "replace":
                result.extend(SentenceDiff(op="insert", text=s) for s in new_sents[j1:j2])
        elif tag == "insert":
            result.extend(SentenceDiff(op="insert", text=s) for s in new_sents[j1:j2])
    return result


def _split_sentences(text: str) -> List[str]:
    parts = _SENTENCE_END.split(text)
    return [part.strip() for part in parts if part.strip()]
