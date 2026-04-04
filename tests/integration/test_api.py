"""Integration tests for the FastAPI API layer.

Uses ``httpx.AsyncClient`` with the ASGI transport — no real LLM or CadQuery.
``MockLLMBackend`` and ``MockSandbox`` are injected via a test-specific
``CADPipeline``.

Run with::

    pytest tests/integration/test_api.py -v
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from caid_lite.api.server import create_app
from caid_lite.executor.result import ExecutionResult
from caid_lite.pipeline import CADPipeline
from caid_lite.session.manager import SessionManager
from tests.fixtures.mock_llm import MockLLMBackend
from tests.fixtures.mock_sandbox import MockSandbox

# ── Fixtures ──────────────────────────────────────────────────────────────────

_FENCED_CODE = "```python\nimport cadquery as cq\n\ndef build_model():\n    return cq.Workplane('XY').box(1,1,1)\n```"

_VALID_METRICS = {
    "is_valid": True, "is_solid": True, "volume": 1000.0,
    "face_count": 6, "bbox": [10.0, 10.0, 10.0],
}


def _make_exec(success=True, exception=None, metrics=None):
    return ExecutionResult(
        run_id="test", success=success, stdout="", stderr="",
        exception=exception, exports={}, elapsed_s=0.01,
        validation_metrics=metrics,
    )


def _make_test_app(llm_responses=None, exec_results=None):
    """Build a FastAPI app wired with mock LLM and sandbox.

    State is set directly on the app rather than via a lifespan, because
    ``httpx.ASGITransport`` does not trigger ASGI lifespan events.
    """
    responses = llm_responses or [_FENCED_CODE]
    results = exec_results or [_make_exec(metrics=_VALID_METRICS)]

    llm = MockLLMBackend(responses=responses)
    sandbox = MockSandbox(results=results)
    pipeline = CADPipeline(llm=llm, sandbox=sandbox)
    manager = SessionManager(pipeline=pipeline)

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from caid_lite.api.routes import chat, events, parts, workspace

    test_app = FastAPI()
    test_app.state.manager = manager  # inject directly; no lifespan needed
    test_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    test_app.include_router(chat.router, prefix="/api")
    test_app.include_router(parts.router, prefix="/api")
    test_app.include_router(workspace.router, prefix="/api")
    test_app.include_router(events.router, prefix="/api")
    return test_app


@pytest_asyncio.fixture
async def client():
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── POST /api/chat ────────────────────────────────────────────────────────────


class TestPostChat:
    async def test_returns_part_id(self, client):
        r = await client.post("/api/chat", json={"message": "a simple box"})
        assert r.status_code == 200
        assert "part_id" in r.json()

    async def test_part_id_is_non_empty_string(self, client):
        r = await client.post("/api/chat", json={"message": "a box"})
        assert isinstance(r.json()["part_id"], str)
        assert len(r.json()["part_id"]) > 8

    async def test_empty_message_returns_422(self, client):
        r = await client.post("/api/chat", json={"message": ""})
        assert r.status_code == 422

    async def test_missing_message_field_returns_422(self, client):
        r = await client.post("/api/chat", json={})
        assert r.status_code == 422

    async def test_part_appears_in_parts_list(self, client):
        r = await client.post("/api/chat", json={"message": "a box"})
        part_id = r.json()["part_id"]
        await asyncio.sleep(0.05)  # let background task run
        parts_r = await client.get("/api/parts")
        ids = [p["id"] for p in parts_r.json()]
        assert part_id in ids


# ── GET /api/parts ────────────────────────────────────────────────────────────


class TestGetParts:
    async def test_empty_list_initially(self, client):
        r = await client.get("/api/parts")
        assert r.status_code == 200
        assert r.json() == []

    async def test_returns_list_after_submission(self, client):
        await client.post("/api/chat", json={"message": "a box"})
        await asyncio.sleep(0.05)
        r = await client.get("/api/parts")
        assert isinstance(r.json(), list)
        assert len(r.json()) >= 1

    async def test_part_has_required_fields(self, client):
        await client.post("/api/chat", json={"message": "a bracket"})
        await asyncio.sleep(0.05)
        r = await client.get("/api/parts")
        part = r.json()[0]
        for key in ("id", "name", "prompt", "status", "created_at"):
            assert key in part


# ── GET /api/parts/{id} ───────────────────────────────────────────────────────


class TestGetPart:
    async def test_returns_part_by_id(self, client):
        r = await client.post("/api/chat", json={"message": "a box"})
        part_id = r.json()["part_id"]
        await asyncio.sleep(0.05)
        r2 = await client.get(f"/api/parts/{part_id}")
        assert r2.status_code == 200
        assert r2.json()["id"] == part_id

    async def test_unknown_id_returns_404(self, client):
        r = await client.get("/api/parts/nonexistent-id")
        assert r.status_code == 404

    async def test_prompt_preserved_in_part(self, client):
        r = await client.post("/api/chat", json={"message": "a mounting bracket"})
        part_id = r.json()["part_id"]
        await asyncio.sleep(0.05)
        r2 = await client.get(f"/api/parts/{part_id}")
        assert r2.json()["prompt"] == "a mounting bracket"


# ── DELETE /api/parts/{id} ────────────────────────────────────────────────────


class TestDeletePart:
    async def test_delete_returns_204(self, client):
        r = await client.post("/api/chat", json={"message": "a box"})
        part_id = r.json()["part_id"]
        await asyncio.sleep(0.05)
        r2 = await client.delete(f"/api/parts/{part_id}")
        assert r2.status_code == 204

    async def test_part_gone_after_delete(self, client):
        r = await client.post("/api/chat", json={"message": "a box"})
        part_id = r.json()["part_id"]
        await asyncio.sleep(0.05)
        await client.delete(f"/api/parts/{part_id}")
        r2 = await client.get(f"/api/parts/{part_id}")
        assert r2.status_code == 404

    async def test_delete_unknown_id_returns_404(self, client):
        r = await client.delete("/api/parts/unknown-id")
        assert r.status_code == 404


# ── GET /api/parts/{id}/step and /stl ─────────────────────────────────────────


class TestWorkspaceRoutes:
    async def test_step_not_ready_returns_409(self, client):
        r = await client.post("/api/chat", json={"message": "a box"})
        part_id = r.json()["part_id"]
        # Do NOT sleep — part is still generating
        r2 = await client.get(f"/api/parts/{part_id}/step")
        # Either 404 (still generating, no exports) or 409 (not ready)
        assert r2.status_code in (404, 409)

    async def test_step_unknown_part_returns_404(self, client):
        r = await client.get("/api/parts/unknown/step")
        assert r.status_code == 404

    async def test_stl_unknown_part_returns_404(self, client):
        r = await client.get("/api/parts/unknown/stl")
        assert r.status_code == 404


# ── GET /api/events ───────────────────────────────────────────────────────────
#
# httpx's ASGITransport buffers the full response body before returning it,
# so an infinite SSE stream never completes.  We work around this by using a
# _FiniteStreamManager whose event_stream() yields at most ``max_events``
# events and then returns.  Once the generator exhausts, Starlette sends a
# final ``more_body=False`` chunk, response_complete is set, and httpx can
# deliver the complete (finite) response.


import json as _json_mod


def _parse_sse_body(text: str) -> list:
    """Parse an SSE response body into a list of event dicts."""
    events = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                events.append(_json_mod.loads(line[5:].strip()))
            except _json_mod.JSONDecodeError:
                pass
    return events


def _make_sse_test_app(llm_responses=None, exec_results=None, max_events: int = 5):
    """Build a test app with a finite SSE stream (compatible with ASGITransport)."""
    from caid_lite.session.manager import SessionManager as _SM

    responses = llm_responses or [_FENCED_CODE]
    results = exec_results or [_make_exec(metrics=_VALID_METRICS)]

    llm = MockLLMBackend(responses=responses)
    sandbox = MockSandbox(results=results)
    pipeline = CADPipeline(llm=llm, sandbox=sandbox)

    class _FiniteManager(_SM):
        async def event_stream(self, q):
            import json
            for _ in range(max_events):
                try:
                    event = await asyncio.wait_for(q.get(), timeout=2.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    break  # no event within window — end the stream

    manager = _FiniteManager(pipeline=pipeline)

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from caid_lite.api.routes import chat, events, parts, workspace

    test_app = FastAPI()
    test_app.state.manager = manager
    test_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    test_app.include_router(chat.router, prefix="/api")
    test_app.include_router(parts.router, prefix="/api")
    test_app.include_router(workspace.router, prefix="/api")
    test_app.include_router(events.router, prefix="/api")
    return test_app


class TestEventsRoute:
    async def test_events_status_and_content_type(self):
        """SSE endpoint returns 200 with text/event-stream content type."""
        app = _make_sse_test_app(max_events=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/events")
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]

    async def test_events_initial_event_is_connected(self):
        """First event on a new SSE connection is type='connected'."""
        app = _make_sse_test_app(max_events=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/events")
        events = _parse_sse_body(r.text)
        assert len(events) >= 1
        assert events[0]["type"] == "connected"

    async def test_events_emit_after_chat(self):
        """Posting to /api/chat causes part status events on the SSE stream.

        Both the SSE GET and the chat POST run concurrently via asyncio.gather.
        The finite stream (max_events=5, timeout=2s) suspends waiting for queue
        items, giving the POST coroutine time to run and emit events.
        """
        app = _make_sse_test_app(max_events=5)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            async def _post_chat():
                await asyncio.sleep(0.05)  # let the SSE stream start first
                await c.post("/api/chat", json={"message": "a box"})

            _, r = await asyncio.gather(_post_chat(), c.get("/api/events"))

        events = _parse_sse_body(r.text)
        assert len(events) >= 2
        types = {e["type"] for e in events}
        assert types & {"part.status_changed", "part.ready", "part.failed"}
