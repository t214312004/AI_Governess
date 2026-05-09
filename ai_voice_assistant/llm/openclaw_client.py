import json
import time
import httpx
from httpx_sse import aconnect_sse
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from .base_client import BaseLLMClient, STREAM_ACTIVITY_KEEPALIVE

class OpenClawClient(BaseLLMClient):
    """
    OpenClaw API client with SSE streaming support.
    """
    def __init__(
        self,
        api_url: str,
        token: str = "",
        agent_id: str = "",
        user: str = "voice-assistant",
        model: str = "openclaw",
        message_channel: str = "",
        scopes: str = "",
        request_timeout_seconds: float = 60.0,
    ):
        self.api_url = api_url
        self.headers = {"Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.agent_id = agent_id
        self.model = self._normalize_model(model, agent_id)
        self.user = user
        self.message_channel = message_channel
        self.scopes = scopes
        self.request_timeout_seconds = request_timeout_seconds
        self.previous_response_id = None
        self._cancel_flag = False
        self._client: httpx.AsyncClient | None = None

    @staticmethod
    def _normalize_model(model: str, agent_id: str = "") -> str:
        if model:
            return model
        if agent_id:
            return f"openclaw/{agent_id}"
        return "openclaw"

    def _headers(self) -> dict:
        headers = dict(self.headers)
        if self.agent_id:
            headers["x-openclaw-agent-id"] = self.agent_id
        if self.message_channel:
            headers["x-openclaw-message-channel"] = self.message_channel
        if self.scopes:
            headers["x-openclaw-scopes"] = self.scopes
        return headers

    def _build_payload(self, text: str) -> dict:
        payload = {
            "model": self.model,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                }
            ],
            "user": self.user,
            "stream": True,
        }
        if self.previous_response_id:
            payload["previous_response_id"] = self.previous_response_id
        return payload

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.request_timeout_seconds)
        return self._client

    @asynccontextmanager
    async def _request_client(self):
        yield self._get_client()

    def _remember_response_id(self, data: dict):
        response_id = data.get("id") or data.get("response", {}).get("id")
        if response_id:
            self.previous_response_id = response_id

    @staticmethod
    def _extract_delta(data: dict) -> str:
        return data.get("delta") or data.get("text") or ""

    async def send_message(self, text: str) -> AsyncGenerator[str, None]:
        self._cancel_flag = False
        payload = self._build_payload(text)

        async with self._request_client() as client:
            try:
                async with aconnect_sse(client, "POST", self.api_url, json=payload, headers=self._headers()) as event_source:
                    async for sse in event_source.aiter_sse():
                        if self._cancel_flag:
                            break

                        if sse.data == "[DONE]":
                            break

                        data = {}
                        if sse.data:
                            data = json.loads(sse.data)
                            self._remember_response_id(data)

                        if sse.event == "response.output_text.delta":
                            chunk = self._extract_delta(data)
                            if chunk:
                                yield chunk
                        elif sse.event in {
                            "response.in_progress",
                            "response.output_item.added",
                            "response.content_part.added",
                        }:
                            yield STREAM_ACTIVITY_KEEPALIVE
                        elif sse.event == "response.completed":
                            break
                        elif sse.event == "response.failed":
                            raise RuntimeError(f"OpenClaw 錯誤：{data}")
            except httpx.RequestError as e:
                raise RuntimeError(f"OpenClaw 連線錯誤：{e}")
            except json.JSONDecodeError as e:
                raise RuntimeError(f"OpenClaw SSE JSON 解析錯誤：{e}")

    async def cancel(self):
        self._cancel_flag = True

    async def aclose(self):
        self._cancel_flag = True
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def refresh_session(self) -> bool:
        # OpenResponses has no long-lived session/new; rotate stable user ids instead.
        self.previous_response_id = None
        self.user = f"voice-assistant-{int(time.time())}"
        return True
