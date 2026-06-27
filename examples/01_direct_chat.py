"""Example 1 — the simplest chat, in-process (no server needed).

Use this when your code IS Python and you just want a reply from DeepSeek.

Run it from the project root:

    python examples/01_direct_chat.py

On the very first run a browser window opens for sign-in automatically — sign in
(and solve the human-check); it continues once the session is captured. After
that the session is reused, no window.
"""

# Make the project importable when this file is run directly.
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from deepseek import DeepSeekClient

# Create the client once and reuse it. It loads (or captures) your signed-in
# session automatically.
client = DeepSeekClient()

# .chat() waits for the FULL reply, then returns it.
#
# model picks which model answers: "default" (Instant, the fast default) or
# "expert" (stronger, slower). thinking enables DeepThink reasoning and search
# enables web search; both are independent of the model. All are optional.
reply = client.chat(
    "Say hello in one short sentence.",
    model="expert",
    thinking=True,
)
print(reply.text)
print("conversation_id:", reply.conversation_id)   # pass this back to continue

client.close()
