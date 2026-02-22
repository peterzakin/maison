from __future__ import annotations

import asyncio
import json
import os
import shlex
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from daytona import AsyncDaytona, CreateSandboxFromSnapshotParams
from daytona.common.process import SessionExecuteRequest


@dataclass
class StreamEvent:
    """A single event from Claude Code's stream-json output."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def content(self) -> str:
        """Best-effort extraction of text content from the event."""
        for key in ("content", "text", "result"):
            val = self.data.get(key)
            if isinstance(val, str):
                return val
        msg = self.data.get("message")
        if isinstance(msg, dict):
            for key in ("content", "text"):
                val = msg.get(key)
                if isinstance(val, str):
                    return val
        return ""


class MaisonSandbox:
    """A Daytona sandbox with Claude Code installed and ready to use."""

    def __init__(
        self,
        sandbox: Any,
        daytona: AsyncDaytona,
        anthropic_api_key: str,
    ) -> None:
        self._sandbox = sandbox
        self._daytona = daytona
        self._anthropic_api_key = anthropic_api_key
        self._session_id: Optional[str] = None

    async def _ensure_session(self) -> str:
        """Create a persistent session for running Claude Code commands."""
        if self._session_id is None:
            self._session_id = f"maison-{uuid.uuid4().hex[:8]}"
            await self._sandbox.process.create_session(self._session_id)
        return self._session_id

    async def stream(
        self,
        prompt: str,
        instructions: Optional[str] = None,
        continue_conversation: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Run Claude Code with *prompt* and yield events as they arrive.

        Parameters
        ----------
        prompt:
            The task or question for Claude Code.
        instructions:
            Optional custom instructions appended to Claude Code's system
            prompt.  Use this to steer behaviour, set constraints, or provide
            additional context.
        continue_conversation:
            If ``True``, continue the most recent conversation in this
            sandbox so Claude retains context from previous messages.

        Thinking tokens, text deltas, tool-use events, and the final result
        are all surfaced as ``StreamEvent`` instances.
        """
        session_id = await self._ensure_session()

        escaped_prompt = shlex.quote(prompt)
        optional_flags = ""
        if instructions:
            optional_flags += (
                f" --append-system-prompt {shlex.quote(instructions)}"
            )
        if continue_conversation:
            optional_flags += " --continue"
        cmd = (
            f"ANTHROPIC_API_KEY={shlex.quote(self._anthropic_api_key)} "
            f"claude --dangerously-skip-permissions "
            f"-p {escaped_prompt} "
            f"--output-format stream-json "
            f"--include-partial-messages"
            f"{optional_flags}"
        )

        # Run the command asynchronously so we can stream logs.
        resp = await self._sandbox.process.execute_session_command(
            session_id,
            SessionExecuteRequest(command=cmd, run_async=True),
        )
        cmd_id = resp.cmd_id

        queue: asyncio.Queue[Optional[dict[str, Any]]] = asyncio.Queue()
        buffer: list[str] = []

        def _parse_lines(text: str) -> None:
            buffer.append(text)
            combined = "".join(buffer)
            while "\n" in combined:
                line, combined = combined.split("\n", 1)
                stripped = line.strip()
                if stripped:
                    try:
                        queue.put_nowait(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
            buffer.clear()
            if combined:
                buffer.append(combined)

        def _on_stdout(data: str) -> None:
            _parse_lines(data)

        def _on_stderr(data: str) -> None:
            pass  # Ignore stderr for event parsing.

        async def _follow_logs() -> None:
            try:
                await self._sandbox.process.get_session_command_logs_async(
                    session_id, cmd_id, _on_stdout, _on_stderr,
                )
            finally:
                await queue.put(None)

        log_task = asyncio.create_task(_follow_logs())
        try:
            while True:
                raw = await queue.get()
                if raw is None:
                    break
                yield StreamEvent(
                    type=raw.get("type", "unknown"),
                    data=raw,
                )
        finally:
            if not log_task.done():
                log_task.cancel()

    async def read_file(self, path: str) -> str:
        """Read a file from the sandbox filesystem."""
        return await self._sandbox.fs.read_file(path)

    async def close(self) -> None:
        """Delete the sandbox and release resources."""
        await self._daytona.delete(self._sandbox)


class Maison:
    """Create sandboxed environments for running Claude Code safely."""

    @staticmethod
    async def create_sandbox_for_claude(
        *,
        anthropic_api_key: Optional[str] = None,
        snapshot: str = "daytona-small",
        name: Optional[str] = None,
    ) -> MaisonSandbox:
        """Spin up a Daytona sandbox with Claude Code pre-installed.

        Parameters
        ----------
        anthropic_api_key:
            Anthropic API key for Claude.  Falls back to the
            ``ANTHROPIC_API_KEY`` environment variable.
        snapshot:
            Daytona sandbox snapshot image.
        name:
            Optional human-readable sandbox name.

        Returns
        -------
        MaisonSandbox
            A sandbox ready to stream Claude Code tasks.

        Raises
        ------
        ValueError
            If no Anthropic API key is available.
        RuntimeError
            If Claude Code installation fails.
        """
        api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError(
                "An Anthropic API key is required. "
                "Pass anthropic_api_key= or set ANTHROPIC_API_KEY."
            )

        daytona = AsyncDaytona()

        params_kwargs: dict[str, Any] = {"snapshot": snapshot}
        if name:
            params_kwargs["name"] = name
        sandbox = await daytona.create(
            CreateSandboxFromSnapshotParams(**params_kwargs)
        )

        result = await sandbox.process.exec(
            "sudo chown -R $(whoami) $(npm prefix -g) "
            "&& npm install -g @anthropic-ai/claude-code"
        )
        if result.exit_code != 0:
            await daytona.delete(sandbox)
            raise RuntimeError(
                f"Failed to install Claude Code: {result.result}"
            )

        return MaisonSandbox(sandbox, daytona, api_key)
