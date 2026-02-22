from __future__ import annotations

import asyncio
import json
import os
import shlex
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from daytona import AsyncDaytona, CreateSandboxFromSnapshotParams


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
        queue: asyncio.Queue[Optional[dict[str, Any]]] = asyncio.Queue()
        buffer: list[str] = []

        def _on_data(data: bytes) -> None:
            text = data.decode("utf-8", errors="replace")
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

        pty = await self._sandbox.process.create_pty_session(
            id="claude-stream",
            on_data=_on_data,
        )
        await pty.wait_for_connection()

        escaped_prompt = shlex.quote(prompt)
        escaped_key = shlex.quote(self._anthropic_api_key)
        optional_flags = ""
        if instructions:
            optional_flags += (
                f" --append-system-prompt {shlex.quote(instructions)}"
            )
        if continue_conversation:
            optional_flags += " --continue"
        cmd = (
            f"ANTHROPIC_API_KEY={escaped_key} "
            f"claude --dangerously-skip-permissions "
            f"-p {escaped_prompt} "
            f"--output-format stream-json "
            f"--include-partial-messages"
            f"{optional_flags}"
        )
        await pty.send_input(cmd + "\n")

        async def _wait_for_exit() -> None:
            await pty.wait()
            await queue.put(None)

        wait_task = asyncio.create_task(_wait_for_exit())
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
            if not wait_task.done():
                wait_task.cancel()

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
        snapshot: str = "daytonaio/sandbox:latest",
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
            "npm install -g @anthropic-ai/claude-code"
        )
        if result.exit_code != 0:
            await daytona.delete(sandbox)
            raise RuntimeError(
                f"Failed to install Claude Code: {result.output}"
            )

        return MaisonSandbox(sandbox, daytona, api_key)
