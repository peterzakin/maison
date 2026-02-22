# Maison

Run [Claude Code](https://code.claude.com) with `--dangerously-skip-permissions` safely inside a [Daytona](https://www.daytona.io) sandbox.

## Install

```bash
pip install .
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DAYTONA_API_KEY` | Yes | Your [Daytona API key](https://www.daytona.io/docs/en/getting-started/) |
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key (or pass it directly) |

## CLI

```bash
# Interactive chat session
maison-cli

# Single prompt
maison-cli -p "Write a hello world program in Python"

# With custom instructions
maison-cli --instructions "Always use type hints"
```

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
| `snapshot` | `"daytonaio/sandbox:latest"` | Daytona snapshot image |
| `name` | `None` | Optional sandbox name |

### `MaisonSandbox.stream(prompt, ...) -> AsyncIterator[StreamEvent]`

Runs Claude Code with the given prompt and yields `StreamEvent` objects as they arrive. Includes thinking tokens, text deltas, tool use, and the final result.

| Parameter | Default | Description |
|---|---|---|
| `prompt` | *(required)* | The task or question for Claude Code |
| `instructions` | `None` | Custom instructions appended to Claude Code's system prompt |
| `continue_conversation` | `False` | Continue the most recent conversation so Claude retains prior context |

### `MaisonSandbox.read_file(path) -> str`

Reads a file from the sandbox filesystem.

### `MaisonSandbox.close()`

Deletes the sandbox and frees resources.

### `StreamEvent`

| Field | Type | Description |
|---|---|---|
| `type` | `str` | Event type (e.g. `"thinking"`, `"text"`, `"tool_use"`, `"result"`) |
| `data` | `dict` | Raw JSON event from Claude Code |
| `content` | `str` | Convenience property that extracts text content |

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

1. `create_sandbox_for_claude()` spins up an isolated Daytona sandbox and installs Claude Code via npm.
2. `stream()` runs `claude --dangerously-skip-permissions -p <prompt> --output-format stream-json --include-partial-messages` inside the sandbox over a PTY session, parsing the NDJSON output into typed events.
3. Because Claude runs inside the sandbox, it has full permissions without risking your host machine.

## License

MIT
