import json

import httpx
import pytest
import respx

from dispatchzero.integrations.ollama import OllamaClient, OllamaError


def _chat_response(content: str) -> dict:
    return {
        "id": "chatcmpl-test",
        "model": "gpt-oss:120b",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


@pytest.mark.asyncio
async def test_chat_returns_content_string():
    messages = [{"role": "user", "content": "hi"}]
    client = OllamaClient(
        api_key="test-key", base_url="https://ollama.example/v1", model="m"
    )
    with respx.mock:
        respx.post("https://ollama.example/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_chat_response('{"x": 1}'))
        )
        out = await client.chat(messages)
    assert out == '{"x": 1}'


@pytest.mark.asyncio
async def test_chat_sends_bearer_auth_and_model():
    messages = [{"role": "user", "content": "hi"}]
    client = OllamaClient(
        api_key="my-secret", base_url="https://ollama.example/v1", model="m"
    )
    with respx.mock:
        route = respx.post("https://ollama.example/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_chat_response("{}"))
        )
        await client.chat(messages)
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer my-secret"
    body = json.loads(request.read())
    assert body["model"] == "m"
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_chat_retries_once_on_5xx():
    messages = [{"role": "user", "content": "hi"}]
    client = OllamaClient(
        api_key="k", base_url="https://ollama.example/v1", model="m"
    )
    with respx.mock:
        route = respx.post("https://ollama.example/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(200, json=_chat_response("{}")),
            ]
        )
        out = await client.chat(messages)
    assert out == "{}"
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_chat_raises_after_two_5xx():
    messages = [{"role": "user", "content": "hi"}]
    client = OllamaClient(
        api_key="k", base_url="https://ollama.example/v1", model="m"
    )
    with respx.mock:
        respx.post("https://ollama.example/v1/chat/completions").mock(
            return_value=httpx.Response(503)
        )
        with pytest.raises(OllamaError):
            await client.chat(messages)


@pytest.mark.asyncio
async def test_chat_raises_immediately_on_4xx():
    messages = [{"role": "user", "content": "hi"}]
    client = OllamaClient(
        api_key="bad", base_url="https://ollama.example/v1", model="m"
    )
    with respx.mock:
        route = respx.post("https://ollama.example/v1/chat/completions").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        with pytest.raises(OllamaError):
            await client.chat(messages)
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_chat_raises_when_no_api_key():
    client = OllamaClient(
        api_key="", base_url="https://ollama.example/v1", model="m"
    )
    with pytest.raises(OllamaError, match="api key"):
        await client.chat([{"role": "user", "content": "x"}])
