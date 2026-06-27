"""Example 2 — a multi-turn conversation, in-process.

Every reply carries a `conversation_id`. Pass it back on the next call to
continue the SAME conversation, so the model sees the earlier turns. The id is
opaque — it encodes both the chat session and the message to continue from.

Run it from the project root:

    python examples/02_direct_conversation.py
"""

# Make the project importable when this file is run directly.
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import time

from deepseek import DeepSeekClient

client = DeepSeekClient()

# Turn 1 — no id given, so this starts a NEW conversation and returns its id.
first = client.chat("My name is Meao. Remember it.")
print("DeepSeek:", first.text)
print("conversation_id:", first.conversation_id)

time.sleep(3)  # be gentle — one shared client serves requests serially

# Turn 2 — pass the id back to CONTINUE the same conversation.
second = client.chat("What's my name? Reply with just the name.",
                     conversation_id=first.conversation_id)
print("DeepSeek:", second.text)  # -> recalls "Meao"

client.close()
