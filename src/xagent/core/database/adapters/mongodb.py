"""MongoDB adapter。"""

from __future__ import annotations

import json
import time
from typing import Any

from .base import DatabaseAdapter, QueryExecutionResult


def _normalize_document(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): _normalize_document(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_document(item) for item in value]
    return value


class MongoDbAdapter(DatabaseAdapter):
    family = "mongodb"
    supported_types = ("mongodb",)
    write_operations = {
        "insert_one",
        "insert_many",
        "update_one",
        "update_many",
        "delete_one",
        "delete_many",
    }

    def __init__(self, config):
        super().__init__(config)
        self._client = None

    def _get_client(self):
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise ImportError(
                "pymongo is required for MongoDbAdapter. Install it with: pip install pymongo"
            ) from exc

        if self._client is None:
            extra = dict(self.config.extra or {})
            self._client = MongoClient(
                host=self.config.host or "localhost",
                port=self.config.port or 27017,
                username=self.config.user,
                password=self.config.password,
                **extra,
            )
        return self._client

    def _get_database(self):
        database_name = self.config.database
        if not database_name:
            raise ValueError("MongoDB adapter requires a database name.")
        return self._get_client()[database_name]

    def _parse_query(self, query: str) -> dict[str, Any]:
        try:
            payload = json.loads(query)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "MongoDB query must be a JSON object, for example "
                '{"collection":"users","operation":"find","filter":{"status":"active"}}'
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError("MongoDB query payload must be a JSON object.")
        return payload

    async def connect(self) -> None:
        self._get_client()

    async def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    async def execute_query(
        self, query: str, params: list[Any] | dict[str, Any] | None = None
    ) -> QueryExecutionResult:
        payload = self._parse_query(query)
        operation = str(payload.get("operation", "find")).lower()
        if self.config.read_only and self.is_write_operation(operation):
            raise PermissionError("Database 'mongodb' is configured as read-only.")

        collection_name = payload.get("collection")
        if not collection_name:
            raise ValueError("MongoDB query payload must contain 'collection'.")
        collection = self._get_database()[collection_name]
        started = time.perf_counter()

        if operation == "find":
            cursor = collection.find(
                payload.get("filter", {}),
                payload.get("projection"),
            )
            for field, direction in payload.get("sort", []):
                cursor = cursor.sort(field, direction)
            if payload.get("limit"):
                cursor = cursor.limit(int(payload["limit"]))
            rows = [_normalize_document(doc) for doc in cursor]
            elapsed = int((time.perf_counter() - started) * 1000)
            return QueryExecutionResult(
                rows=rows,
                affected_rows=len(rows),
                execution_time_ms=elapsed,
                metadata={"family": self.family, "operation": operation},
            )

        if operation == "aggregate":
            rows = [
                _normalize_document(doc)
                for doc in collection.aggregate(payload.get("pipeline", []))
            ]
            elapsed = int((time.perf_counter() - started) * 1000)
            return QueryExecutionResult(
                rows=rows,
                affected_rows=len(rows),
                execution_time_ms=elapsed,
                metadata={"family": self.family, "operation": operation},
            )

        if operation == "insert_one":
            result = collection.insert_one(payload["document"])
            elapsed = int((time.perf_counter() - started) * 1000)
            return QueryExecutionResult(
                rows=[{"inserted_id": str(result.inserted_id)}],
                affected_rows=1,
                execution_time_ms=elapsed,
                metadata={"family": self.family, "operation": operation},
            )

        if operation == "update_many":
            result = collection.update_many(
                payload.get("filter", {}), payload.get("update", {})
            )
            elapsed = int((time.perf_counter() - started) * 1000)
            return QueryExecutionResult(
                rows=[],
                affected_rows=result.modified_count,
                execution_time_ms=elapsed,
                metadata={"family": self.family, "matched_count": result.matched_count},
            )

        if operation == "delete_many":
            result = collection.delete_many(payload.get("filter", {}))
            elapsed = int((time.perf_counter() - started) * 1000)
            return QueryExecutionResult(
                rows=[],
                affected_rows=result.deleted_count,
                execution_time_ms=elapsed,
                metadata={"family": self.family, "operation": operation},
            )

        raise ValueError(f"Unsupported MongoDB operation: {operation}")

    async def get_schema(self) -> dict[str, Any]:
        database = self._get_database()
        collections = []
        for collection_name in database.list_collection_names():
            sample = database[collection_name].find_one()
            fields = []
            if isinstance(sample, dict):
                fields = [
                    {"name": key, "type": type(value).__name__}
                    for key, value in sample.items()
                ]
            collections.append({"collection": collection_name, "fields": fields})
        return {
            "databaseType": self.config.db_type,
            "family": self.family,
            "collections": collections,
        }

    def is_write_operation(self, query: str) -> bool:
        return query.strip().lower() in self.write_operations
