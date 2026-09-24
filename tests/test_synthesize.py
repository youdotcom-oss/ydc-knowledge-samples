"""Offline tests for synthesis model routing and Blackbox stream parsing."""

from __future__ import annotations

import os

os.environ.setdefault("YDC_API_KEY", "test-key")

import pytest

from utils.synthesize import (
    BLACKBOX_MODELS,
    BLACKBOX_URL,
    MODEL,
    backend_for,
    blackbox_body,
    read_chat_stream,
)


def test_default_model_is_openrouter_luna():
    backend, model, label = backend_for(None)
    assert backend == "openrouter"
    assert model == MODEL
    assert label == "GPT-5.6 Luna"


@pytest.mark.parametrize("model", list(BLACKBOX_MODELS))
def test_blackbox_models_route_to_blackbox(model):
    backend, model_id, label = backend_for(model)
    assert backend == "blackbox"
    assert model_id == model
    assert label == BLACKBOX_MODELS[model]


def test_unknown_model_names_the_known_ones():
    with pytest.raises(ValueError, match="unknown model"):
        backend_for("not-a-model")


def test_blackbox_body_streams_the_selected_model():
    body = blackbox_body(
        "moonshotai/kimi-k3",
        [{"role": "user", "content": "Hello, Blackbox!"}],
    )
    assert body == {
        "model": "moonshotai/kimi-k3",
        "messages": [{"role": "user", "content": "Hello, Blackbox!"}],
        "stream": True,
    }
    assert BLACKBOX_URL == "https://enterprise.blackbox.ai/chat/completions"


def test_read_chat_stream_joins_deltas_and_keeps_usage():
    lines = [
        "",
        'data: {"choices":[{"delta":{"content":"Hello"}}]}',
        'data: {"choices":[{"delta":{"content":", Blackbox!"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2}}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":" ignored"}}]}',
    ]
    text, usage = read_chat_stream(lines)
    assert text == "Hello, Blackbox!"
    assert usage["prompt_tokens"] == 3
    assert usage["completion_tokens"] == 2


def test_read_chat_stream_raises_on_error_event():
    lines = ['data: {"error":{"message":"bad key"}}']
    with pytest.raises(ValueError, match="bad key"):
        read_chat_stream(lines)
