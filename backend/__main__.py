"""Entry point: ``python -m backend``.

Configures logging and runs the FastAPI app under uvicorn.
"""

from __future__ import annotations

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("BACKEND_PORT", "3000")),
    )


if __name__ == "__main__":
    main()
