"""Entry point — run the OpenAI-compatible DeepSeek server.

    python app.py            # serves on http://localhost:8000

On first use (no saved session) a browser window opens for you to sign in by
hand; run `python -m deepseek.auth` to do that ahead of time. Set
DEEPSEEK_PROFILE_DIR to reuse an existing signed-in Chrome profile.
"""

import logging
import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG
    if os.getenv("LOG_LEVEL", "").upper() == "DEBUG"
    else logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)

if __name__ == "__main__":
    uvicorn.run(
        "server.api:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
        log_level="info",
    )
