import json

import httpx
import pytest

from memory.embeddings import EmbeddingError, OllamaEmbeddingConfig, OllamaEmbeddingProvider


def fake_transport(handler):
    return httpx.MockTransport(handler)


def test_embed_posts_explicit_model_to_local_ollama_and_normalizes_numbers():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"embeddings": [[1, 2.5], [3.0, 4]]})

    provider = OllamaEmbeddingProvider(
        OllamaEmbeddingConfig(model="locally-selected-model"), transport=fake_transport(handler)
    )

    assert provider.embed(["first", "second"]) == [[1.0, 2.5], [3.0, 4.0]]
    assert seen == {
        "url": "http://127.0.0.1:11434/api/embed",
        "payload": {"model": "locally-selected-model", "input": ["first", "second"]},
    }


def test_config_requires_explicit_model_and_stays_loopback():
    with pytest.raises(EmbeddingError, match="OLLAMA_EMBEDDING_MODEL"):
        OllamaEmbeddingConfig.from_environ({})
    with pytest.raises(EmbeddingError, match="loopback"):
        OllamaEmbeddingConfig(model="a-local-model", base_url="https://example.com")

    config = OllamaEmbeddingConfig.from_environ({"OLLAMA_EMBEDDING_MODEL": "chosen-by-user"})
    assert config.model == "chosen-by-user"


def test_embed_supports_legacy_single_vector_response():
    provider = OllamaEmbeddingProvider(
        OllamaEmbeddingConfig(model="chosen"),
        transport=fake_transport(lambda request: httpx.Response(200, json={"embedding": [1, 2]})),
    )

    assert provider.embed_one("hello") == [1.0, 2.0]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("{\"embeddings\":[[1,NaN]]}", "non-finite"),
        ({"embeddings": [[1, True]]}, "non-numeric"),
        ({"embeddings": [[1], [2, 3]]}, "inconsistent"),
        ({"embeddings": []}, "unexpected number"),
    ],
)
def test_embed_rejects_malformed_vectors(payload, message):
    def handler(request):
        if isinstance(payload, str):
            return httpx.Response(200, content=payload, headers={"content-type": "application/json"})
        return httpx.Response(200, json=payload)

    provider = OllamaEmbeddingProvider(
        OllamaEmbeddingConfig(model="chosen"),
        transport=fake_transport(handler),
    )

    with pytest.raises(EmbeddingError, match=message):
        provider.embed(["hello", "again"] if message == "inconsistent" else ["hello"])


def test_unavailable_ollama_error_is_actionable_and_non_secret():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    provider = OllamaEmbeddingProvider(
        OllamaEmbeddingConfig(model="chosen"), transport=fake_transport(handler)
    )

    with pytest.raises(EmbeddingError, match="Start Ollama"):
        provider.embed(["hello"])


def test_http_model_failure_does_not_include_response_body():
    provider = OllamaEmbeddingProvider(
        OllamaEmbeddingConfig(model="chosen"),
        transport=fake_transport(lambda request: httpx.Response(404, text="do-not-expose-this-body")),
    )

    with pytest.raises(EmbeddingError, match="HTTP 404") as error:
        provider.embed(["hello"])

    assert "do-not-expose-this-body" not in str(error.value)
