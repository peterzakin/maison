"""Multi-turn conversation with Claude Code in a sandbox.

Demonstrates how to build an app that collects user input and sends
multiple sequential messages to Claude, with Claude retaining full
context from earlier turns.
"""

import asyncio

from maison import Maison, StreamEvent


async def main() -> None:
    sandbox = await Maison.create_sandbox_for_claude()

    print("Connected to sandbox. Type your messages below.")
    print("Type 'quit' to exit.\n")

    is_first_message = True
    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "quit":
            break

        print("Claude: ", end="", flush=True)
        async for event in sandbox.stream(
            prompt=user_input,
            # First message starts a new conversation;
            # subsequent messages continue it so Claude has full context.
            continue_conversation=not is_first_message,
        ):
            if event.type == "text":
                print(event.content, end="", flush=True)
        print("\n")

        is_first_message = False

    await sandbox.close()
    print("Sandbox closed.")


if __name__ == "__main__":
    asyncio.run(main())
