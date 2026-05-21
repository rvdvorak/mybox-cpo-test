"""Entry point: ``python -m simulator``.

Loads config from the environment, wires SIGTERM/SIGINT to a graceful stop and
runs the station instance until shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from .config import StationConfig
from .instance import StationInstance


async def _amain() -> None:
    config = StationConfig.from_env()
    instance = StationInstance(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, instance.request_stop)

    await instance.run()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
