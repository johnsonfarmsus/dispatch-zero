import httpx


class OllamaError(RuntimeError):
    """Raised when Ollama Cloud rejects the request or fails persistently."""


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
        """Call chat-completions in JSON mode. Returns the assistant's content string."""
        if not self._api_key:
            raise OllamaError("ollama api key is not configured")

        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.8,
        }
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
