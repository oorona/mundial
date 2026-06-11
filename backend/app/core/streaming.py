"""Server-Sent Events (SSE) helpers — the sanctioned framework streaming path.

Plugins that need server→client push (e.g. a live feed) return
:func:`sse_response` from an ordinary router route, and the frontend consumes it
with ``subscribeSSE`` from ``frontend/lib/streaming.ts``. The plugin validator
allows ``sse_response``/``StreamingResponse`` in plugin ``api.py`` and
``subscribeSSE`` on the client; raw ``EventSource`` stays restricted to
public/activity pages.

Typical Redis-stream tail route
-------------------------------
    from fastapi import APIRouter, Request, Depends
    from app.core.streaming import sse_response, redis_stream_source
    from app.db.redis import get_redis

    @router.get("/{guild_id}/feed/stream")
    async def feed_stream(guild_id: int, request: Request, redis=Depends(get_redis)):
        # NOTE: a high-frequency stream should live under an audit-exempt or
        # non-/guilds/{id}/ prefix — see the audit-volume guidance.
        source = redis_stream_source(redis, f"feed:{guild_id}", request)
        return sse_response(source)

The producer side just appends to the stream:
    await redis.xadd(f"feed:{guild_id}", {"data": json.dumps(event)})
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Optional, Union

from fastapi import Request
from starlette.responses import StreamingResponse

# Event items yielded by a source generator may be a plain string (sent as the
# `data:` field) or a dict describing the SSE frame.
SSEEvent = Union[str, dict]

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Disable proxy buffering (nginx) so events flush immediately.
    "X-Accel-Buffering": "no",
}


def format_sse(data: Any, *, event: Optional[str] = None, id: Optional[str] = None) -> str:
    """Format one SSE frame. Non-string ``data`` is JSON-encoded."""
    if not isinstance(data, str):
        data = json.dumps(data)
    lines = []
    if id is not None:
        lines.append(f"id: {id}")
    if event is not None:
        lines.append(f"event: {event}")
    # Multi-line payloads need a `data:` prefix per line.
    for line in data.split("\n"):
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


async def _wrap(source: AsyncIterator[SSEEvent]) -> AsyncIterator[str]:
    async for item in source:
        if isinstance(item, dict):
            yield format_sse(
                item.get("data", ""),
                event=item.get("event"),
                id=item.get("id"),
            )
        else:
            yield format_sse(item)


def sse_response(source: AsyncIterator[SSEEvent]) -> StreamingResponse:
    """Wrap an async generator of events in a ``text/event-stream`` response."""
    return StreamingResponse(
        _wrap(source),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


async def redis_stream_source(
    redis,
    stream_key: str,
    request: Request,
    *,
    last_id: str = "$",
    block_ms: int = 15000,
) -> AsyncIterator[dict]:
    """Tail a Redis stream and yield each entry as an SSE event dict.

    Uses ``XREAD BLOCK`` so it sleeps until new entries arrive (or ``block_ms``
    elapses, at which point we emit a keep-alive comment and re-check whether the
    client has disconnected). Stops cleanly when the client goes away.

    Each entry is yielded as ``{"id": <stream id>, "data": <fields>}``. If a
    field named ``data`` holds JSON it is decoded; otherwise the raw field map
    is sent.
    """
    cursor = last_id
    while True:
        if await request.is_disconnected():
            return
        try:
            result = await redis.xread({stream_key: cursor}, block=block_ms, count=64)
        except asyncio.CancelledError:  # client disconnected mid-read
            return
        if not result:
            # Keep-alive comment line; also a natural disconnect-check point.
            yield {"data": "", "event": "ping"}
            continue
        for _stream, entries in result:
            for entry_id, fields in entries:
                cursor = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                payload = _decode_fields(fields)
                yield {"id": cursor, "data": payload}


def _decode_fields(fields: dict) -> Any:
    decoded = {
        (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
        for k, v in fields.items()
    }
    if "data" in decoded and isinstance(decoded["data"], str):
        try:
            return json.loads(decoded["data"])
        except (ValueError, TypeError):
            return decoded["data"]
    return decoded
