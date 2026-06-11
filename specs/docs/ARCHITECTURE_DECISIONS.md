# Architecture Decision: Bot Database Access

## Decision

**The Discord bot has DIRECT database access** using the same SQLAlchemy models and database service as the backend.

## Rationale

### Why Direct Access?

1. **Flexibility for Cogs**
   - Cogs can define their own database tables
   - No need to predict all possible API endpoints
   - Faster development (no API endpoints for every query)

2. **Performance**
   - No API overhead for database operations
   - Lower latency for bot commands
   - Fewer network hops

3. **Shared Code**
   - Bot and backend use same SQLAlchemy models
   - Single source of truth for database schema
   - Consistent data access patterns

4. **LLM Cost Tracking**
   - Bot can directly log LLM usage to database
   - Real-time cost tracking without API calls
   - Simpler implementation

### When to Use Backend API?

The backend API is still important for:
- **UI Features**: Frontend needs data (via REST API)
- **Analytics**: Aggregated LLM usage, shard status
- **User Management**: Permission delegation, auth
- **Cross-Service Operations**: Features that span bot and UI

## Network Architecture (Corrected)

```
┌─────────────────────────────────────────────┐
│         Docker Network: internet            │
│  ┌──────────────────────────────────────┐   │
│  │  Frontend (Next.js)                  │   │
│  │  - Public facing                     │   │
│  │  - OAuth callback                    │   │
│  └──────────────────────────────────────┘   │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────┴───────────────────────────┐
│         Docker Network: intranet            │
│  ┌──────────────────────────────────────┐   │
│  │  Backend API (FastAPI)               │◄──┼─ Frontend API calls
│  │  - Stateless                         │   │
│  │  - REST API                          │   │
│  │  - Accesses all 3 networks           │   │
│  └─────────┬────────────────────────────┘   │
│            │                                 │
│  ┌─────────┴────────────────────────────┐   │
│  │  Discord Bot                         │   │
│  │  - AutoShardedBot                    │   │
│  │  - Direct DB access                  │   │
│  │  - Cog loading                       │   │
│  └───────────────────────────────────────┘  │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────┴───────────────────────────┐
│         Docker Network: dbnet               │
│  ┌──────────────────────────────────────┐   │
│  │  PostgreSQL                          │◄──┼─ Backend & Bot
│  │  - Persistent volume                 │   │
│  │  - Guild-scoped data                 │   │
│  └──────────────────────────────────────┘   │
│  ┌──────────────────────────────────────┐   │
│  │  Redis                               │◄──┼─ Backend & Bot
│  │  - Sessions, cache, shard status     │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

### Network Access Summary

| Service  | internet | intranet | dbnet |
|----------|----------|----------|-------|
| Frontend | ✅       | ✅       | ❌    |
| Backend  | ✅       | ✅       | ✅    |
| Bot      | ❌       | ✅       | ✅    |
| Postgres | ❌       | ❌       | ✅    |
| Redis    | ❌       | ❌       | ✅    |

**Key Points**:
- Frontend is public (internet) and can call backend (intranet)
- Backend has access to ALL 3 networks
- Bot has access to intranet (for backend API if needed) and dbnet (for DB/Redis)
- PostgreSQL and Redis are isolated on dbnet
- Redis is on same network as PostgreSQL for simplicity

## Implementation Details

### Bot Database Service

```python
# bot/services/database.py
class DatabaseService:
    def __init__(self, database_url: str):
        self.engine = create_async_engine(database_url)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    @asynccontextmanager
    async def session(self):
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
```

### Cog Usage

```python
# bot/cogs/my_cog.py
class MyCog(commands.Cog):
    def __init__(self, bot, services):
        self.services = services
    
    @commands.slash_command()
    async def mycommand(self, ctx):
        # Direct database access
        async with self.services.db.session() as session:
            result = await session.execute(
                select(MyModel).where(
                    MyModel.guild_id == ctx.guild.id
                )
            )
            data = result.scalars().all()
```

### Shared Models

Both bot and backend import from the same models:

```python
# shared/models/guild.py (shared between bot and backend)
class Guild(Base):
    __tablename__ = 'guilds'
    guild_id = Column(BigInteger, primary_key=True)
    guild_name = Column(String)
    added_by_user_id = Column(BigInteger)
```

## Migration Management

- Backend runs Alembic migrations
- Bot uses same database, reads migrated schema
- Both share model definitions
- Changes to schema require updating shared models

## Benefits of This Approach

✅ **Performance**: No API overhead  
✅ **Flexibility**: Cogs can create any tables they need  
✅ **Simplicity**: Direct access is easier than API wrapping  
✅ **Consistency**: Shared models ensure data consistency  
✅ **Scalability**: Bot sharding still works with direct DB access  

## Trade-offs

⚠️ **Business Logic**: Must be careful not to duplicate logic between bot and backend  
⚠️ **Migration Coordination**: Bot and backend must use same schema  
⚠️ **API Still Needed**: For frontend features and analytics  

## Conclusion

Direct database access for the bot is the right choice for a flexible, performant baseline platform. The backend API remains important for UI features and cross-service operations.
