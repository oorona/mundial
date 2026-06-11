"""
predictions — guild-scoped tables for the bracket pool.

`Prediction` holds one user's score prediction for one match (per guild). `PredictionPool`
holds the per-guild pool config (Kicktipp weights, lock lead, enabled). Both are
guild-scoped (RLS enabled in this plugin's migration). `Base` and the SQLAlchemy types
come from backend/app/models.py, where this content is appended at install time. The
scoring engine itself lives in worldcup_data (score_prediction / scoring_rules).
"""
from sqlalchemy import Column, BigInteger, Integer, Float, String, Boolean, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.sql import func as _func


class PredictionPool(Base):  # noqa: F821
    __tablename__ = "prediction_pools"
    __guild_scoped__ = True  # RLS on guild_id

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, unique=True)
    name = Column(String(120), nullable=False, server_default="Quiniela")
    weight_exact = Column(Integer, nullable=False, server_default="4")
    weight_diff = Column(Integer, nullable=False, server_default="3")
    weight_tendency = Column(Integer, nullable=False, server_default="2")
    knockout_multiplier = Column(Float, nullable=False, server_default="2")
    lock_lead_minutes = Column(Integer, nullable=False, server_default="0")
    enabled = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=_func.now())
    updated_at = Column(DateTime(timezone=True), server_default=_func.now(), onupdate=_func.now())


class Prediction(Base):  # noqa: F821
    __tablename__ = "predictions"
    __guild_scoped__ = True  # RLS on guild_id

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    username = Column(String(120))  # denormalized for the leaderboard (no Discord lookup)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    pred_home = Column(Integer, nullable=False)
    pred_away = Column(Integer, nullable=False)
    points = Column(Integer, nullable=False, server_default="0")
    scored_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=_func.now())
    updated_at = Column(DateTime(timezone=True), server_default=_func.now(), onupdate=_func.now())

    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", "match_id", name="uq_prediction_user_match"),
        Index("idx_predictions_guild_match", "guild_id", "match_id"),
        Index("idx_predictions_guild_user", "guild_id", "user_id"),
    )
