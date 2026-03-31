"""SQLite adapter。"""

from __future__ import annotations

from sqlalchemy import URL

from .sqlalchemy_common import SqlAlchemySyncAdapter


class SqliteAdapter(SqlAlchemySyncAdapter):
    family = "sqlite"
    supported_types = ("sqlite",)

    def build_sqlalchemy_url(self) -> URL:
        return URL.create(
            "sqlite",
            database=self.config.file_path or self.config.database or ":memory:",
            query=self.config.extra or {},
        )
