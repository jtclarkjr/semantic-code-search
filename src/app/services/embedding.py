from __future__ import annotations

import hashlib
import threading
from typing import List, Optional, Sequence


class EmbeddingServiceError(RuntimeError):
    """Raised when the embedding backend cannot be loaded or used."""


class EmbeddingService:
    def __init__(
        self,
        model_name: str,
        dimensions: int,
        device: Optional[str] = None,
        use_stub_embeddings: bool = False,
    ) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        self.device = device
        self.use_stub_embeddings = use_stub_embeddings
        self._model_lock = threading.RLock()
        self._tokenizer = None
        self._model = None
        self._torch = None

    def embed_query(self, query: str) -> List[float]:
        return self.embed_texts([query])[0]

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        if self.use_stub_embeddings:
            return [self._hash_embedding(text) for text in texts]
        try:
            with self._model_lock:
                return self._torch_embeddings(texts)
        except EmbeddingServiceError:
            raise
        except Exception as exc:  # pragma: no cover - depends on model/runtime behavior
            raise EmbeddingServiceError("Embedding inference failed.") from exc

    def _torch_embeddings(self, texts: Sequence[str]) -> List[List[float]]:
        self._ensure_model()
        torch = self._torch
        assert torch is not None
        tokenizer = self._tokenizer
        model = self._model
        encoded = tokenizer(
            list(texts),
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        if self.device:
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
        with torch.no_grad():
            outputs = model(**encoded)
            hidden = outputs.last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return [vector.cpu().tolist() for vector in normalized]

    def _ensure_model(self) -> None:
        if self._model is not None and self._tokenizer is not None and self._torch is not None:
            return
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer

            self._torch = torch
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
            self._model = AutoModel.from_pretrained(self.model_name, trust_remote_code=True)
            if self.device:
                self._model.to(self.device)
            self._model.eval()
        except Exception as exc:  # pragma: no cover - depends on local model/runtime state
            raise EmbeddingServiceError(
                "Failed to initialize the embedding model. "
                "For `jinaai/jina-embeddings-v2-base-code`, use `transformers<5` and re-sync the environment."
            ) from exc

    def _hash_embedding(self, text: str) -> List[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = list(digest) * ((self.dimensions // len(digest)) + 1)
        values = [((byte / 255.0) * 2.0) - 1.0 for byte in seed[: self.dimensions]]
        return self._normalize(values)

    def _normalize(self, vector: List[float]) -> List[float]:
        coerced = [float(item) for item in vector]
        length = sum(item * item for item in coerced) ** 0.5 or 1.0
        normalized = [float(item / length) for item in coerced]
        if len(normalized) != self.dimensions:
            raise ValueError(
                f"Embedding dimension mismatch. Expected {self.dimensions}, got {len(normalized)}."
            )
        return normalized
