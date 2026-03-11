import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import torch

from app.services.embedding import EmbeddingService


class FakeTokenizer:
    def __call__(self, texts, **kwargs):
        assert kwargs["return_tensors"] == "pt"
        if texts == ["websocket"]:
            return {
                "input_ids": torch.tensor([[1, 2, 3]]),
                "attention_mask": torch.tensor([[1, 1, 1]]),
            }
        return {
            "input_ids": torch.tensor([[1, 2]]),
            "attention_mask": torch.tensor([[1, 1]]),
        }


class FakeModel:
    def encode(self, texts):
        raise AssertionError("custom encode path should not be used")

    def __call__(self, **kwargs):
        return SimpleNamespace(
            last_hidden_state=torch.tensor(
                [[[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]],
                dtype=torch.float32,
            )
        )


class GuardedFakeModel:
    def __init__(self) -> None:
        self._active_calls = 0
        self._guard = threading.Lock()

    def __call__(self, **kwargs):
        with self._guard:
            self._active_calls += 1
            active_calls = self._active_calls
        try:
            if active_calls > 1:
                raise AssertionError("model inference ran concurrently")
            return SimpleNamespace(
                last_hidden_state=torch.tensor(
                    [[[1.0, 0.0], [0.0, 1.0]]],
                    dtype=torch.float32,
                )
            )
        finally:
            with self._guard:
                self._active_calls -= 1


def test_embedding_service_uses_manual_forward_path_even_if_model_has_encode() -> None:
    service = EmbeddingService(
        model_name="demo",
        dimensions=2,
        use_stub_embeddings=False,
    )
    service._torch = torch
    service._tokenizer = FakeTokenizer()
    service._model = FakeModel()

    vector = service.embed_query("websocket")

    assert len(vector) == 2
    assert all(type(value) is float for value in vector)


def test_embedding_service_serializes_concurrent_model_access() -> None:
    service = EmbeddingService(
        model_name="demo",
        dimensions=2,
        use_stub_embeddings=False,
    )
    service._torch = torch
    service._tokenizer = FakeTokenizer()
    service._model = GuardedFakeModel()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(service.embed_query, "first"),
            executor.submit(service.embed_query, "second"),
        ]
        results = [future.result() for future in futures]

    assert len(results) == 2
    assert all(len(vector) == 2 for vector in results)
