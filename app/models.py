"""Multi-tenant data model. Each Org owns provider Connections (Square source,
QuickBooks destination) with encrypted tokens + a per-tenant account map, and a
history of per-batch SyncRuns.
"""
from __future__ import annotations
import os, json, datetime as dt
from sqlalchemy import (create_engine, String, Integer, Text, DateTime, ForeignKey,
                        UniqueConstraint)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column, relationship,
                            sessionmaker)


class Base(DeclarativeBase):
    pass


def _now():
    # stamped by the app layer; kept simple for the skeleton
    return dt.datetime.now(dt.timezone.utc)


class Org(Base):
    __tablename__ = "orgs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="America/Denver")
    # posting format per tenant: "journal_entry" | "sales_receipt"
    posting_format: Mapped[str] = mapped_column(String(32), default="journal_entry")
    # rollout: "draft_approve" | "auto_post"
    rollout_mode: Mapped[str] = mapped_column(String(32), default="draft_approve")
    connections: Mapped[list["Connection"]] = relationship(back_populates="org")
    runs: Mapped[list["SyncRun"]] = relationship(back_populates="org")


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("org_id", "provider", name="uq_org_provider"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    provider: Mapped[str] = mapped_column(String(32))          # "square" | "qbo"
    environment: Mapped[str] = mapped_column(String(16), default="production")
    realm_or_location: Mapped[str] = mapped_column(String(64), default="")  # QBO realm / Square location
    client_id: Mapped[str] = mapped_column(String(255), default="")
    client_secret: Mapped[str] = mapped_column(String(512), default="")     # encrypted
    refresh_token_enc: Mapped[str] = mapped_column(Text, default="")        # encrypted
    account_map_json: Mapped[str] = mapped_column(Text, default="{}")       # {"Sales":"79",...}
    status: Mapped[str] = mapped_column(String(24), default="connected")
    org: Mapped["Org"] = relationship(back_populates="connections")

    @property
    def account_map(self) -> dict:
        return json.loads(self.account_map_json or "{}")

    @account_map.setter
    def account_map(self, v: dict):
        self.account_map_json = json.dumps(v)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (UniqueConstraint("org_id", "business_date", "batch", name="uq_run"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    business_date: Mapped[str] = mapped_column(String(10))
    batch: Mapped[str] = mapped_column(String(8))             # "cc" | "cash"
    status: Mapped[str] = mapped_column(String(24), default="pending")  # pending|drafted|posted|review|skipped
    doc_number: Mapped[str] = mapped_column(String(40), default="")
    qbo_id: Mapped[str] = mapped_column(String(40), default="")
    deposit: Mapped[str] = mapped_column(String(24), default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    org: Mapped["Org"] = relationship(back_populates="runs")


class Approval(Base):
    """One approval unit = one org's day (both batches). Draft-and-approve gate:
    the pipeline drafts the JEs, this holds the one-click token; posting happens
    only when approved."""
    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("org_id", "business_date", name="uq_approval"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"))
    business_date: Mapped[str] = mapped_column(String(10))
    token: Mapped[str] = mapped_column(String(64), index=True, unique=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|posted|rejected
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


def make_session(url: str | None = None):
    # Prod: DATABASE_URL (Postgres, from the host). Local: a sqlite file.
    url = url or os.environ.get("DATABASE_URL") or "sqlite:///dailyledger.db"
    if url.startswith("postgres"): url = "postgresql+psycopg://" + url.split("://", 1)[1]
    engine = create_engine(url, echo=False, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
