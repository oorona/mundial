"""
Standalone World Cup 2026 data seeder.

Run after `alembic upgrade head` (the container entrypoint does both):

    python seed.py

Connects to the shared Postgres using config.settings, runs seed_defaults in a
single transaction, and prints row counts. Safe to re-run — seeding is idempotent.
"""

import asyncio

from sqlalchemy import func, select

from db.init import seed_defaults
from db.session import async_session, engine
from models.database import GroupStanding, Match, Player, Stadium, Team


async def _count(session, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar_one()


async def main():
    async with async_session() as session:
        await seed_defaults(session)
        await session.commit()

        counts = {
            "stadiums": await _count(session, Stadium),
            "teams": await _count(session, Team),
            "group_standings": await _count(session, GroupStanding),
            "matches": await _count(session, Match),
            "players": await _count(session, Player),
        }

    print("Seed complete. Row counts:")
    for name, n in counts.items():
        print(f"  {name:16} {n}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
