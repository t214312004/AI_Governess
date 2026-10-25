"""Bounded async HTTP operations with cancellation and redacted failures."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import time

import httpx

from utils.gemini_audio import GeminiAPIError, INTERACTIONS_URL, check_response


def cancelled(signal) -> bool:
    return signal is not None and signal.is_set()


async def bounded(awaitable, *, signal=None, deadline: float, timeout: float | None = None):
    """Do not leave a timer context alive while an async generator yields."""
    task = asyncio.ensure_future(awaitable)
    end = min(deadline, time.monotonic() + timeout) if timeout is not None else deadline
    try:
        while not task.done():
            if cancelled(signal):
                raise asyncio.CancelledError
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise GeminiAPIError("timeout")
            await asyncio.wait({task}, timeout=min(.05, remaining))
        if cancelled(signal):
            raise asyncio.CancelledError
        if time.monotonic() > end:
            raise GeminiAPIError("timeout")
        return task.result()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def retry_delay(response: httpx.Response) -> float:
    raw = response.headers.get("retry-after", "")
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            return max(0.0, (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0.0


def response_error(response):
    if response.status_code != 200:
        raise GeminiAPIError("http_error", response.status_code, retry_delay(response))


def retryable(error):
    return (isinstance(error, httpx.TransportError) or
        isinstance(error, GeminiAPIError) and error.status_code is not None and
        (error.status_code == 429 or 500 <= error.status_code <= 599))


def safe_error(error):
    if isinstance(error, GeminiAPIError):
        return error
    return GeminiAPIError("network_error" if isinstance(error, httpx.HTTPError) else "invalid_response")


async def backoff(error, attempt, *, signal, deadline):
    delay = max(getattr(error, "retry_after", 0), min(2.0, .5 * 2**attempt))
    if time.monotonic()+delay >= deadline:
        raise safe_error(error) from None
    await bounded(asyncio.sleep(delay), signal=signal, deadline=deadline)


async def request_json(payload, api_key, settings, *, signal=None, diagnostics=None):
    deadline = time.monotonic()+settings["total_timeout_seconds"]
    timeout = httpx.Timeout(settings.get("request_timeout_seconds", settings["total_timeout_seconds"]),
                            connect=settings["connect_timeout_seconds"])
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(settings["max_retries"]+1):
            if diagnostics is not None:
                diagnostics["attempts"] = attempt+1
            try:
                response = await bounded(client.post(INTERACTIONS_URL,
                    headers={"x-goog-api-key": api_key}, json=payload), signal=signal,
                    deadline=deadline, timeout=settings.get("request_timeout_seconds"))
                response_error(response)
                return check_response(response)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if attempt >= settings["max_retries"] or not retryable(exc):
                    raise safe_error(exc) from None
                await backoff(exc, attempt, signal=signal, deadline=deadline)


async def async_sse_messages(lines):
    data = []
    async for line in lines:
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif not line and data:
            raw, data = "\n".join(data), []
            if raw != "[DONE]":
                yield json.loads(raw)
    if data and "\n".join(data) != "[DONE]":
        yield json.loads("\n".join(data))
