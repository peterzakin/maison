"""Tests for maison.sandbox – unit tests and live integration tests."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from maison.sandbox import MaisonSandbox, StreamEvent

# ---------------------------------------------------------------------------
# Unit tests – StreamEvent.content extraction
# ---------------------------------------------------------------------------


class TestStreamEventContent:
    def test_content_from_content_key(self):
        e = StreamEvent(type="text", data={"content": "hello"})
        assert e.content == "hello"

    def test_content_from_text_key(self):
        e = StreamEvent(type="text", data={"text": "world"})
        assert e.content == "world"

    def test_content_from_result_key(self):
        e = StreamEvent(type="result", data={"result": "done"})
        assert e.content == "done"

    def test_content_from_nested_message(self):
        e = StreamEvent(
            type="text",
            data={"message": {"content": "nested"}},
        )
        assert e.content == "nested"

    def test_content_returns_empty_string_when_missing(self):
        e = StreamEvent(type="unknown", data={"foo": "bar"})
        assert e.content == ""

    def test_content_prefers_top_level_over_nested(self):
        e = StreamEvent(
            type="text",
            data={"content": "top", "message": {"content": "nested"}},
        )
        assert e.content == "top"

    def test_content_skips_non_string_values(self):
        e = StreamEvent(type="text", data={"content": 42, "text": "fallback"})
        assert e.content == "fallback"


# ---------------------------------------------------------------------------
# Helpers for mocking the Daytona sandbox filesystem + process
# ---------------------------------------------------------------------------


@dataclass
class FakeSessionExecResponse:
    cmd_id: str = "cmd-123"
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None


class FakeFS:
    """Simulates sandbox.fs with in-memory files."""

    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    async def download_file(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path].encode("utf-8")


class FakeProcess:
    """Simulates sandbox.process for the file-polling stream approach."""

    def __init__(
        self,
        fs: FakeFS,
        out_lines: list[str],
        err_text: str = "",
        exit_code: int = 0,
    ) -> None:
        self._fs = fs
        self._out_lines = out_lines
        self._err_text = err_text
        self._exit_code = exit_code
        self.created_sessions: list[str] = []
        self.executed_commands: list[str] = []

    async def create_session(self, session_id: str) -> None:
        self.created_sessions.append(session_id)

    async def execute_session_command(
        self, session_id: str, req: Any
    ) -> FakeSessionExecResponse:
        self.executed_commands.append(req.command)
        # Pre-flight check
        if "which claude" in req.command:
            return FakeSessionExecResponse(
                cmd_id="verify-cmd",
                exit_code=0,
                stdout="/usr/local/bin/claude\n",
            )
        # For the actual claude command, simulate writing output files
        # after a short delay (mimics async file writing).
        asyncio.get_event_loop().call_soon(
            lambda: asyncio.ensure_future(
                self._write_output_files(req.command)
            )
        )
        return FakeSessionExecResponse(cmd_id="cmd-123")

    async def _write_output_files(self, command: str) -> None:
        """Parse file paths from the command and write simulated output."""
        # Extract file paths from the redirect command:
        #   ... > /tmp/maison-XXX.jsonl 2> /tmp/maison-XXX.err; echo $? > /tmp/maison-XXX.done
        import re

        out_match = re.search(r"> (/tmp/maison-\S+\.jsonl)", command)
        err_match = re.search(r"2> (/tmp/maison-\S+\.err)", command)
        done_match = re.search(r"> (/tmp/maison-\S+\.done)", command)
        if not (out_match and err_match and done_match):
            return

        out_path = out_match.group(1)
        err_path = err_match.group(1)
        done_path = done_match.group(1)

        # Write output incrementally to simulate streaming.
        content = ""
        for line in self._out_lines:
            await asyncio.sleep(0)
            content += line
            self._fs.files[out_path] = content

        # Write stderr and done marker.
        await asyncio.sleep(0)
        self._fs.files[err_path] = self._err_text
        self._fs.files[done_path] = str(self._exit_code)


def _make_sandbox(
    out_lines: list[str],
    err_text: str = "",
    exit_code: int = 0,
) -> MaisonSandbox:
    fs = FakeFS()
    process = FakeProcess(fs, out_lines, err_text, exit_code)
    fake_sandbox = MagicMock()
    fake_sandbox.process = process
    fake_sandbox.fs = fs
    fake_daytona = AsyncMock()
    return MaisonSandbox(fake_sandbox, fake_daytona, "sk-test-key")


# ---------------------------------------------------------------------------
# Unit tests – file-polling stream()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_yields_parsed_ndjson_events():
    """Verify that NDJSON lines in the output file produce StreamEvents."""
    lines = [
        json.dumps({"type": "text", "content": "Hello"}) + "\n",
        json.dumps({"type": "text", "content": " world"}) + "\n",
        json.dumps({"type": "result", "result": "done"}) + "\n",
    ]
    sb = _make_sandbox(out_lines=lines)

    events: list[StreamEvent] = []
    async for event in sb.stream("hi", poll_interval=0.01):
        events.append(event)

    text_events = [e for e in events if e.type != "stderr"]
    assert len(text_events) == 3
    assert text_events[0].type == "text"
    assert text_events[0].content == "Hello"
    assert text_events[1].content == " world"
    assert text_events[2].type == "result"
    assert text_events[2].content == "done"


@pytest.mark.asyncio
async def test_stream_handles_multiple_lines_in_one_chunk():
    """Multiple NDJSON lines written at once should all be parsed."""
    # Write all lines in a single string (simulates batch write)
    combined = (
        json.dumps({"type": "text", "content": "a"}) + "\n"
        + json.dumps({"type": "text", "content": "b"}) + "\n"
    )
    sb = _make_sandbox(out_lines=[combined])

    events = [e async for e in sb.stream("hi", poll_interval=0.01)]
    text_events = [e for e in events if e.type != "stderr"]
    assert len(text_events) == 2
    assert text_events[0].content == "a"
    assert text_events[1].content == "b"


@pytest.mark.asyncio
async def test_stream_skips_malformed_json():
    """Non-JSON lines should be silently skipped."""
    lines = [
        "this is not json\n",
        json.dumps({"type": "text", "content": "ok"}) + "\n",
    ]
    sb = _make_sandbox(out_lines=lines)

    events = [e async for e in sb.stream("hi", poll_interval=0.01)]
    text_events = [e for e in events if e.type != "stderr"]
    assert len(text_events) == 1
    assert text_events[0].content == "ok"


@pytest.mark.asyncio
async def test_stream_surfaces_stderr_as_events():
    """Stderr file content should appear as a 'stderr' type event."""
    stdout = [json.dumps({"type": "text", "content": "hi"}) + "\n"]
    sb = _make_sandbox(out_lines=stdout, err_text="Error: something went wrong")

    events = [e async for e in sb.stream("hi", poll_interval=0.01)]
    stderr_events = [e for e in events if e.type == "stderr"]
    assert len(stderr_events) == 1
    assert "something went wrong" in stderr_events[0].content


@pytest.mark.asyncio
async def test_stream_no_output_completes():
    """If the command produces no output, stream should end cleanly."""
    sb = _make_sandbox(out_lines=[])

    events = [e async for e in sb.stream("hi", poll_interval=0.01)]
    # May have empty stderr event or nothing at all
    text_events = [e for e in events if e.type != "stderr"]
    assert text_events == []


@pytest.mark.asyncio
async def test_verify_claude_fails_raises_runtime_error():
    """If 'which claude' fails, stream should raise RuntimeError."""
    fs = FakeFS()
    process = FakeProcess(fs, out_lines=[])

    # Override execute_session_command to fail the which check
    original = process.execute_session_command

    async def failing_exec(session_id, req):
        if "which claude" in req.command:
            return FakeSessionExecResponse(
                cmd_id="verify-cmd", exit_code=1, stdout="", stderr="not found"
            )
        return await original(session_id, req)

    process.execute_session_command = failing_exec

    fake_sandbox = MagicMock()
    fake_sandbox.process = process
    fake_sandbox.fs = fs
    fake_daytona = AsyncMock()
    sb = MaisonSandbox(fake_sandbox, fake_daytona, "sk-test-key")

    with pytest.raises(RuntimeError, match="claude binary not found"):
        async for _ in sb.stream("hi", poll_interval=0.01):
            pass


@pytest.mark.asyncio
async def test_session_reused_across_calls():
    """Multiple stream() calls should reuse the same session."""
    lines = [json.dumps({"type": "text", "content": "ok"}) + "\n"]
    sb = _make_sandbox(out_lines=lines)

    # First call
    _ = [e async for e in sb.stream("first", poll_interval=0.01)]
    session_id_1 = sb._session_id

    # Reset fake output for second call
    sb._sandbox.process._out_lines = list(lines)
    _ = [
        e
        async for e in sb.stream(
            "second", continue_conversation=True, poll_interval=0.01
        )
    ]
    session_id_2 = sb._session_id

    assert session_id_1 == session_id_2
    assert session_id_1 is not None


@pytest.mark.asyncio
async def test_stream_command_includes_continue_flag():
    """continue_conversation=True should add --continue to the command."""
    lines = [json.dumps({"type": "text", "content": "ok"}) + "\n"]
    sb = _make_sandbox(out_lines=lines)

    # First call (no continue)
    _ = [e async for e in sb.stream("first", poll_interval=0.01)]
    cmd1 = sb._sandbox.process.executed_commands[-1]
    assert "--continue" not in cmd1

    # Second call with continue
    sb._sandbox.process._out_lines = list(lines)
    _ = [
        e
        async for e in sb.stream(
            "second", continue_conversation=True, poll_interval=0.01
        )
    ]
    cmd2 = sb._sandbox.process.executed_commands[-1]
    assert "--continue" in cmd2


@pytest.mark.asyncio
async def test_stream_command_includes_instructions():
    """Instructions should be passed via --append-system-prompt."""
    lines = [json.dumps({"type": "text", "content": "ok"}) + "\n"]
    sb = _make_sandbox(out_lines=lines)

    _ = [
        e
        async for e in sb.stream(
            "hi", instructions="Be concise", poll_interval=0.01
        )
    ]
    cmd = sb._sandbox.process.executed_commands[-1]
    assert "--append-system-prompt" in cmd
    assert "Be concise" in cmd


@pytest.mark.asyncio
async def test_stream_command_redirects_to_files():
    """The command should redirect stdout/stderr to temp files."""
    lines = [json.dumps({"type": "text", "content": "ok"}) + "\n"]
    sb = _make_sandbox(out_lines=lines)

    _ = [e async for e in sb.stream("hi", poll_interval=0.01)]
    cmd = sb._sandbox.process.executed_commands[-1]
    assert "> /tmp/maison-" in cmd
    assert "2> /tmp/maison-" in cmd
    assert "echo $? > /tmp/maison-" in cmd


# ---------------------------------------------------------------------------
# Integration test – requires live Daytona + Anthropic credentials
# ---------------------------------------------------------------------------

LIVE_TEST = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") or not os.environ.get("DAYTONA_API_KEY"),
    reason="ANTHROPIC_API_KEY and DAYTONA_API_KEY required for live tests",
)


@LIVE_TEST
@pytest.mark.asyncio
async def test_live_sandbox_stream():
    """End-to-end: create a sandbox, send a prompt, verify events arrive."""
    from maison import Maison

    sandbox = await Maison.create_sandbox_for_claude()
    try:
        events: list[StreamEvent] = []
        async for event in sandbox.stream("Say exactly: hello test"):
            events.append(event)
            print(f"[{event.type}] {event.data}")

        # We should have received at least one event.
        assert len(events) > 0, "No events received from Claude"

        # Check for text content or stderr errors.
        text_events = [e for e in events if e.type != "stderr"]
        stderr_events = [e for e in events if e.type == "stderr"]

        if stderr_events:
            stderr_text = " ".join(e.content for e in stderr_events)
            print(f"stderr: {stderr_text}")

        # Should have some text content.
        all_content = "".join(e.content for e in text_events)
        assert len(all_content) > 0, f"No text content in events: {events}"
        print(f"\nClaude response: {all_content}")
    finally:
        await sandbox.close()
