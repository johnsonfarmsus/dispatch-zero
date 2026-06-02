"""OpenAI-compatible chat client.

Speaks to anything that implements `POST /v1/chat/completions` — Ollama Cloud,
a self-hosted Ollama runtime, OpenAI, Together.ai, etc. The base URL + model
are env-configured (see config.Settings), so swapping providers is a config
change, not a code change.

Two output modes:

- `chat(messages)`: legacy `response_format={"type":"json_object"}`. The
  model is told to return JSON but the grammar is unconstrained — it may
  still produce invalid JSON, extra prose, markdown fences, etc.
- `chat_structured(messages, schema)`: grammar-forced output via
  `response_format={"type":"json_schema", "json_schema":{...}}`. The
  decoder is constrained to emit only tokens that keep the partial output
  valid against the schema. Use this for any production code path that
  has to parse the result.

Schemas passed to `chat_structured` should describe SHAPE only (required
fields, types, nullability). Don't put length/range constraints in the
grammar — Ollama's structured-output backend (llama.cpp) crashes on some
of them. Validate semantics (min/max length, regex patterns) in Pydantic
after parsing instead, and use a repair retry there.

Nullable fields MUST use `anyOf: [{"type":"string"}, {"type":"null"}]`,
not `type: ["string", "null"]` — the latter trips llama.cpp's GBNF
generator on the OLMo 2 runtime we deploy against.
"""
import httpx


class OllamaError(RuntimeError):
    """Raised when the chat endpoint rejects the request or fails persistently."""


class OllamaClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int = 15,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._http = http_client or httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={
                "User-Agent": "dispatchzero/0.1 (trevor@johnsonfarms.us)",
            },
        )
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """Call chat-completions in unconstrained JSON-object mode."""
        payload = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.8,
        }
        return await self._post_chat(payload)

    async def chat_structured(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict,
        schema_name: str = "structured_output",
        temperature: float = 0.8,
    ) -> str:
        """Call chat-completions with a JSON-schema grammar constraint.

        The model's output is grammar-forced to be a JSON value that matches
        `schema`. Returns the raw content string (still a JSON string —
        caller parses + Pydantic-validates).

        `strict: true` is sent to providers that honor it (OpenAI). Ollama's
        llama.cpp backend ignores the flag and just enforces the schema
        unconditionally. Either way, you get grammar-forced output.
        """
        payload = {
            "model": self._model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
            "temperature": temperature,
        }
        return await self._post_chat(payload)

    async def _post_chat(self, payload: dict) -> str:
        """Shared POST + transport retry for both chat modes."""
        if not self._api_key:
            raise OllamaError("ollama api key is not configured")

        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                r = await self._http.post(url, json=payload, headers=headers)
            except httpx.TransportError as e:
                last_exc = e
                if attempt == 2:
                    raise OllamaError(f"ollama transport failed: {e}") from e
                continue

            if r.status_code >= 500:
                if attempt == 2:
                    raise OllamaError(f"ollama 5xx: {r.status_code} {r.text[:200]}")
                continue
            if r.status_code >= 400:
                raise OllamaError(f"ollama 4xx: {r.status_code} {r.text[:200]}")

            data = r.json()
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as e:
                raise OllamaError(f"unexpected ollama response shape: {data}") from e

        raise OllamaError(f"ollama failed after retries: {last_exc}")
