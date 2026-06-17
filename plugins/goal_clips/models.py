"""
goal_clips — global table for goal video clips ingested from the Fox browser extension.

NOT guild-scoped: a goal clip is identical for every server, so it is stored once and
fanned out to each guild's goal channel by the live_tracker cog. No RLS (see migration).
`Base` and the SQLAlchemy types come from backend/app/models.py, where this content is
appended at install time.
"""
from sqlalchemy import Column, BigInteger, Integer, Float, String, Text, DateTime, Index
from sqlalchemy.sql import func as _func


class GoalClip(Base):  # noqa: F821
    __tablename__ = "goal_clips"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tweet_id = Column(String(64), nullable=False, unique=True)   # source post id — dedup key
    tweet_url = Column(String(512))
    text = Column(Text)                                          # raw post text the client classified
    # Parsed from the post text by the client LLM (best-effort, all nullable).
    home_team = Column(String(120))
    away_team = Column(String(120))
    home_score = Column(Integer)
    away_score = Column(Integer)
    scorer = Column(String(160))
    minute = Column(String(16))
    confidence = Column(Float)
    # Storage + lifecycle.
    file_path = Column(String(512), nullable=False)             # /data/videos/{tweet_id}.mp4
    content_type = Column(String(80), server_default="video/mp4")
    match_id = Column(Integer)                                  # resolved by the bot (nullable until paired)
    status = Column(String(20), nullable=False, server_default="received")  # received|posted|expired
    created_at = Column(DateTime(timezone=True), server_default=_func.now())
    posted_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_goal_clips_status", "status"),
        Index("idx_goal_clips_match", "match_id"),
    )
