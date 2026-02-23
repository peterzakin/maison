# Maison

Run [Claude Code](https://code.claude.com) with `--dangerously-skip-permissions` safely inside a [Daytona](https://www.daytona.io) sandbox.

## Install

```bash
pip install .
```

Requires Python 3.10 or later.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DAYTONA_API_KEY` | Yes | Your [Daytona API key](https://www.daytona.io/docs/en/getting-started/) (read by the Daytona SDK) |
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key (or pass it directly via `anthropic_api_key=`) |

These variables are read by their respective SDKs, not by Maison directly. The Daytona SDK also supports optional `DAYTONA_API_URL` and `DAYTONA_TARGET` variables for custom deployments.

## CLI

After installing, the `maison-cli` command is available. It spins up a Daytona sandbox, installs Claude Code, and connects you to it.

### Interactive mode

Run `maison-cli` with no arguments to start a multi-turn chat session. Claude retains context across messages, and the sandbox is automatically deleted when you type `quit` or press Ctrl+C.

```bash
maison-cli
```

### One-shot mode

Pass `-p` to run a single prompt and exit:

```bash
maison-cli -p "Write a hello world program in Python"
```

### Options

| Flag | Description |
|---|---|
| `-p`, `--prompt` | Run a single prompt and exit |
| `--instructions` | Custom instructions appended to Claude's system prompt |
| `--snapshot` | Daytona sandbox image (default: `daytona-small`) |
| `--debug` | Print raw event data for debugging |

## Quick start

```python
import asyncio
from maison import Maison

async def main():
    sandbox = await Maison.create_sandbox_for_claude()

    # Stream thinking tokens and output from Claude
    async for event in sandbox.stream("Write a hello world program in Python"):
        print(f"[{event.type}] {event.content}")

    # Pass custom instructions to steer Claude's behaviour
    async for event in sandbox.stream(
        "Build a REST API for a todo app",
        instructions="Always use type hints. Write tests for every endpoint.",
    ):
        print(f"[{event.type}] {event.content}")

    # Read a file Claude created inside the sandbox
    code = await sandbox.read_file("/home/daytona/hello.py")
    print(code)

    await sandbox.close()

asyncio.run(main())
```

## API

### `Maison.create_sandbox_for_claude(**kwargs) -> MaisonSandbox`

Creates a Daytona sandbox and installs Claude Code.

| Parameter | Default | Description |
|---|---|---|
| `anthropic_api_key` | `$ANTHROPIC_API_KEY` | Anthropic API key |
| `snapshot` | `"daytona-small"` | Daytona snapshot image |
| `name` | `None` | Optional sandbox name |

**Raises:** `ValueError` if no Anthropic API key is provided or found in `$ANTHROPIC_API_KEY`. `RuntimeError` if Node.js or Claude Code installation fails in the sandbox.

### `MaisonSandbox.stream(prompt, ...) -> AsyncIterator[StreamEvent]`

Runs Claude Code with the given prompt and yields `StreamEvent` objects as they arrive. Includes thinking tokens, text deltas, tool use, and the final result.

| Parameter | Default | Description |
|---|---|---|
| `prompt` | *(required)* | The task or question for Claude Code |
| `instructions` | `None` | Custom instructions appended to Claude Code's system prompt |
| `continue_conversation` | `False` | Continue the most recent conversation so Claude retains prior context |
| `poll_interval` | `0.3` | Seconds between file polls for new output |

**Raises:** `RuntimeError` if the `claude` binary is not found in the sandbox (checked on first call).

### `MaisonSandbox.read_file(path) -> str`

Reads a file from the sandbox filesystem.

### `MaisonSandbox.close()`

Deletes the sandbox and frees resources.

### `StreamEvent`

| Field | Type | Description |
|---|---|---|
| `type` | `str` | Event type: `"thinking"`, `"text"`, `"tool_use"`, `"result"`, or `"stderr"` |
| `data` | `dict` | Raw JSON event from Claude Code |
| `content` | `str` | Convenience property that extracts text content |

A `"stderr"` event is emitted at the end of a `stream()` call if Claude Code wrote anything to stderr.

## Multi-turn conversations

Use `continue_conversation=True` to send follow-up messages that retain full context from earlier turns:

```python
sandbox = await Maison.create_sandbox_for_claude()

# First message — starts a new conversation
async for event in sandbox.stream("Create a Python Flask app with a /health endpoint"):
    if event.type == "text":
        print(event.content, end="")

# Second message — continues the same conversation
async for event in sandbox.stream(
    "Now add a /users endpoint with GET and POST",
    continue_conversation=True,
):
    if event.type == "text":
        print(event.content, end="")
```

See [`examples/multi_turn.py`](examples/multi_turn.py) for a complete interactive chat loop.

## How it works

1. `create_sandbox_for_claude()` spins up an isolated Daytona sandbox, installs Node.js (if needed), and installs Claude Code globally via npm.
2. `stream()` creates a persistent Daytona session (reused across calls for multi-turn) and runs `claude --dangerously-skip-permissions -p <prompt> --output-format stream-json --verbose` with output redirected to temporary files.
3. Maison polls the output file for new NDJSON lines at a configurable interval (default 0.3 s), parsing each line into a `StreamEvent`. A completion marker file signals the end of the stream.
4. Because Claude runs inside the sandbox, it has full permissions without risking your host machine.

## License

MIT
