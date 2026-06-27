"""Example 3 — stream the reply as it is generated, in-process.

client.stream() yields pieces of text as they arrive, instead of waiting for the
whole reply. Good for showing output live (like a chat UI typing).

Run it from the project root:

    python examples/03_direct_stream.py
"""

# Make the project importable when this file is run directly.
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from deepseek import DeepSeekClient

client = DeepSeekClient()

# Omit conversation_id to start fresh. Each chunk is a string; the
# conversation_id is filled in once the stream finishes.
stream = client.stream("Tell me a short, clean joke.")
for chunk in stream:
    print(chunk, end="", flush=True)

print()  # newline after the streamed text
print("conversation_id:", stream.conversation_id)
client.close()
