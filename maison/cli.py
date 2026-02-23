"""Interactive CLI for running Claude Code in a Daytona sandbox."""

from __future__ import annotations

import argparse
import asyncio
import sys

from maison import Maison, StreamEvent


async def run(args: argparse.Namespace) -> None:
    print("Creating sandbox...", flush=True)
    sandbox = await Maison.create_sandbox_for_claude(
        snapshot=args.snapshot,
    )
    print("Sandbox ready.\n", flush=True)

    is_first_message = True
    try:
        def print_event(event: StreamEvent) -> None:
            if args.debug:
                print(f"\n[DEBUG {event.type}] {event.data}", flush=True)
            if event.type == "stderr":
                print(
                    f"\n[stderr] {event.content}",
                    file=sys.stderr,
                    flush=True,
                )
                return
            content = event.content
            if content:
                print(content, end="", flush=True)

        # One-shot mode: run a single prompt and exit.
        if args.prompt:
            async for event in sandbox.stream(
                args.prompt,
                instructions=args.instructions,
            ):
                print_event(event)
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
                print_event(event)
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
        default="daytona-small",
        help="Daytona snapshot image (default: daytona-small).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print raw event data for debugging.",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
