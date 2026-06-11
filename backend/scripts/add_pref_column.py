import asyncio
from sqlalchemy import text
from app.db.session import engine

async def migrate():
    async with engine.begin() as conn:
        print("Adding preferences column to users table...")
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS preferences JSON DEFAULT '{}'"))
        print("Done.")

if __name__ == "__main__":
    asyncio.run(migrate())
