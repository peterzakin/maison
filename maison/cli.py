"""Interactive CLI for running Claude Code in a Daytona sandbox."""

from __future__ import annotations

import argparse
import asyncio
import sys

from maison import Maison


async def run(args: argparse.Namespace) -> None:
    print("Creating sandbox...", flush=True)
    sandbox = await Maison.create_sandbox_for_claude(
        snapshot=args.snapshot,
    )
    print("Sandbox ready.\n", flush=True)

    is_first_message = True
    try:
        # One-shot mode: run a single prompt and exit.
        if args.prompt:
            async for event in sandbox.stream(
                args.prompt,
                instructions=args.instructions,
            ):
                if event.type == "text":
                    print(event.content, end="", flush=True)
            print()
            return

        # Interactive mode: read-eval-print loop.
        print("Type a message to send to Claude. Type 'quit' to exit.\n")
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user_input:
                continue
            if user_input.lower() == "quit":
                break

            print("Claude: ", end="", flush=True)
            async for event in sandbox.stream(
                user_input,
                instructions=args.instructions,
                continue_conversation=not is_first_message,
            ):
                if event.type == "text":
                    print(event.content, end="", flush=True)
            print("\n")
            is_first_message = False
    finally:
        print("Deleting sandbox...", flush=True)
        await sandbox.close()
        print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="maison-cli",
        description="Run Claude Code in a Daytona sandbox.",
    )
    parser.add_argument(
        "-p", "--prompt",
        help="Run a single prompt and exit (non-interactive mode).",
    )
    parser.add_argument(
        "--instructions",
        help="Custom instructions appended to Claude's system prompt.",
    )
    parser.add_argument(
        "--snapshot",
        default="daytonaio/sandbox:latest",
        help="Daytona snapshot image (default: daytonaio/sandbox:latest).",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
