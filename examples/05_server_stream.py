"""Example 5 — stream from the server over HTTP (Server-Sent Events).

Streaming needs TWO things: "stream": true in the JSON body (so the server sends
SSE), and stream=True on the request (so you can read it piece by piece).

Install requests first:

    pip install requests

Start the server in another terminal:

    python app.py

Then run this from the project root:

    python examples/05_server_stream.py

The server sends lines like `data: {...}`; the text is in
choices[0].delta.content, the conversation_id arrives on the final chunk, and
the stream ends with `data: [DONE]`.
"""

import json

import requests

URL = "http://localhost:8000/v1/chat/completions"

with requests.post(URL, json={
    "model": "deepseek-chat",
    "stream": True,
    "messages": [{"role": "user", "content": "Tell me a short, clean joke."}],
}, stream=True) as response:
    conversation_id = None
    for line in response.iter_lines():
        if not line or not line.startswith(b"data: "):
            continue
        payload = line[len("data: "):]
        if payload == b"[DONE]":      # end of the stream
            break
        chunk = json.loads(payload)
        piece = chunk["choices"][0]["delta"].get("content")
        if piece:
            print(piece, end="", flush=True)
        if chunk.get("conversation_id"):   # present on the final chunk
            conversation_id = chunk["conversation_id"]

print()
print("conversation_id:", conversation_id)
