import asyncio
import hashlib
import os
import re
from pathlib import Path
from typing import List

import numpy as np
from loguru import logger

from app.core.settings.app import AppSettings
from app.services.ai.errors import AIServiceError

TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class EmbeddingClient:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._model = None
        self._model_load_attempted = False
        self._use_hash_fallback = False

    @property
    def model_name(self) -> str:
        if self._should_skip_model_loading():
            return self._fallback_model_name

        return self._settings.embedding_model

    @property
    def dimensions(self) -> int:
        return self._settings.embedding_dimensions

    async def embed_text(self, text: str) -> List[float]:
        try:
            if self._use_hash_fallback or self._should_skip_model_loading():
                self._use_hash_fallback = True
                return self._embed_text_with_hashing(text)

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._embed_text_sync, text)
        except Exception as exc:
            raise AIServiceError("embedding generation failed: {0}".format(exc)) from exc

    def _embed_text_sync(self, text: str) -> List[float]:
        model = self._get_model()
        if model is None:
            return self._embed_text_with_hashing(text)

        chunks = self._chunk_text(text)
        vectors = model.encode(chunks, normalize_embeddings=True)
        vector = np.mean(vectors, axis=0)
        norm = np.linalg.norm(vector)
        if norm:
            vector = vector / norm

        return vector.astype(float).tolist()

    def _get_model(self):
        if self._use_hash_fallback or self._should_skip_model_loading():
            self._use_hash_fallback = True
            return None

        if self._model is None:
            self._model_load_attempted = True
            try:
                from sentence_transformers import SentenceTransformer
                import inspect

                if not self._settings.embedding_allow_download:
                    os.environ["HF_HUB_OFFLINE"] = "1"
                    os.environ["TRANSFORMERS_OFFLINE"] = "1"
                    os.environ["HF_DATASETS_OFFLINE"] = "1"

                init_kwargs = {
                    "cache_folder": self._settings.embedding_cache_folder or None,
                }
                if "local_files_only" in inspect.signature(
                    SentenceTransformer.__init__,
                ).parameters:
                    init_kwargs["local_files_only"] = (
                        not self._settings.embedding_allow_download
                    )

                self._model = SentenceTransformer(
                    self._settings.embedding_model,
                    **init_kwargs,
                )
            except Exception as exc:
                if not self._settings.embedding_fallback_enabled:
                    raise

                self._use_hash_fallback = True
                logger.warning(
                    "Falling back to hashing embeddings because model {0} could "
                    "not be loaded: {1}",
                    self._settings.embedding_model,
                    exc,
                )
                return None

        return self._model

    def _chunk_text(self, text: str) -> List[str]:
        words = text.split()
        if not words:
            return [text or "empty article"]

        chunk_size = 180
        return [
            " ".join(words[index : index + chunk_size])
            for index in range(0, len(words), chunk_size)
        ]

    @property
    def _fallback_model_name(self) -> str:
        return "hashing-fallback-{0}".format(self._settings.embedding_dimensions)

    def _should_skip_model_loading(self) -> bool:
        if self._use_hash_fallback:
            return True
        if self._settings.embedding_allow_download:
            return False
        if not self._settings.embedding_fallback_enabled:
            return False

        model_path = Path(self._settings.embedding_model).expanduser()
        if model_path.exists():
            return False

        return not self._has_cached_sentence_transformer_snapshot()

    def _has_cached_sentence_transformer_snapshot(self) -> bool:
        cache_root = self._settings.embedding_cache_folder
        hub_root = (
            Path(cache_root).expanduser()
            if cache_root
            else Path.home() / ".cache" / "huggingface" / "hub"
        )
        cache_name = "models--{0}".format(
            self._settings.embedding_model.replace("/", "--"),
        )
        snapshot_root = hub_root / cache_name / "snapshots"
        if not snapshot_root.exists():
            return False

        return any(
            (snapshot / "modules.json").exists()
            for snapshot in snapshot_root.iterdir()
        )

    def _embed_text_with_hashing(self, text: str) -> List[float]:
        vector = np.zeros(self._settings.embedding_dimensions, dtype=float)
        tokens = TOKEN_RE.findall(text.lower())
        if not tokens:
            tokens = ["empty", "article"]

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = (
                int.from_bytes(digest[:4], "big")
                % self._settings.embedding_dimensions
            )
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = np.linalg.norm(vector)
        if norm:
            vector = vector / norm

        return vector.astype(float).tolist()


class FakeEmbeddingClient:
    model_name = "fake-embedding"
    dimensions = 384

    async def embed_text(self, text: str) -> List[float]:
        seed = sum(ord(char) for char in text) or 1
        vector = [float((seed + index) % 17) for index in range(self.dimensions)]
        norm = sum(value * value for value in vector) ** 0.5
        return [value / norm for value in vector]
