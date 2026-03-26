"""SQL Server adapter。"""

from __future__ import annotations

from sqlalchemy import URL

from .sqlalchemy_common import SqlAlchemySyncAdapter


class SqlServerAdapter(SqlAlchemySyncAdapter):
    family = "sqlserver"
    supported_types = ("sqlserver",)

    def build_sqlalchemy_url(self) -> URL:
        extra = dict(self.config.extra or {})
        if extra.get("odbc_driver"):
            driver = extra.pop("odbc_driver")
            query = {
                "driver": driver,
                "TrustServerCertificate": extra.pop(
                    "TrustServerCertificate", "yes"
                ),
                **extra,
            }
            return URL.create(
                "mssql+pyodbc",
                username=self.config.user,
                password=self.config.password,
                host=self.config.host,
                port=self.config.port or 1433,
                database=self.config.database,
                query=query,
            )

        return URL.create(
            "mssql+pymssql",
            username=self.config.user,
            password=self.config.password,
            host=self.config.host,
            port=self.config.port or 1433,
            database=self.config.database,
            query=extra,
        )
