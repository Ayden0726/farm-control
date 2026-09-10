"""Standalone scheduler worker for Docker Compose."""

import asyncio
import logging

from app.db import Base, engine
from app.main import _scheduler_loop
from app.util import configure_logging

logger = logging.getLogger("farmos.worker")


async def main() -> None:
    configure_logging()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("FarmOS worker starting")
    await _scheduler_loop()


if __name__ == "__main__":
    asyncio.run(main())
