"""PostgreSQL 兼容族 adapter。"""

from __future__ import annotations

from sqlalchemy import URL

from .sqlalchemy_common import SqlAlchemySyncAdapter


class PostgresFamilyAdapter(SqlAlchemySyncAdapter):
    family = "postgresql"
    supported_types = ("postgresql", "kingbase", "gaussdb", "vastbase", "highgo")

    def build_sqlalchemy_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg2",
            username=self.config.user,
            password=self.config.password,
            host=self.config.host,
            port=self.config.port or 5432,
            database=self.config.database,
            query=self.config.extra or {},
        )
