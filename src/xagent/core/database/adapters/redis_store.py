"""Redis adapter。"""

from __future__ import annotations

import json
import time
from typing import Any

from .base import DatabaseAdapter, QueryExecutionResult


def _decode_redis_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, list):
        return [_decode_redis_value(item) for item in value]
    if isinstance(value, tuple):
        return [_decode_redis_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _decode_redis_value(key): _decode_redis_value(val)
            for key, val in value.items()
        }
    return value


class RedisAdapter(DatabaseAdapter):
    family = "redis"
    supported_types = ("redis",)
    write_commands = {"set", "del", "delete", "hset", "hmset", "lpush", "rpush", "zadd"}

    def __init__(self, config):
        super().__init__(config)
        self._client = None

    def _get_client(self):
        try:
            import redis
        except ImportError as exc:
            raise ImportError(
                "redis is required for RedisAdapter. Install it with: pip install redis"
            ) from exc

        if self._client is None:
            extra = dict(self.config.extra or {})
            self._client = redis.Redis(
                host=self.config.host or "localhost",
                port=self.config.port or 6379,
                username=self.config.user,
                password=self.config.password,
                db=int(self.config.database or 0),
                decode_responses=False,
                **extra,
            )
        return self._client

    def _parse_query(self, query: str) -> tuple[str, list[Any]]:
        try:
            payload = json.loads(query)
        except json.JSONDecodeError as exc:
            raise ValueError(
                'Redis query must be JSON, for example {"command":"GET","args":["demo:key"]}'
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError("Redis query payload must be a JSON object.")
        command = str(payload.get("command", "")).strip()
        if not command:
            raise ValueError("Redis query payload must contain 'command'.")
        args = payload.get("args", [])
        if not isinstance(args, list):
            raise ValueError("Redis query payload field 'args' must be a list.")
        return command.upper(), args

    async def connect(self) -> None:
        self._get_client()

    async def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    async def execute_query(
        self, query: str, params: list[Any] | dict[str, Any] | None = None
    ) -> QueryExecutionResult:
        command, args = self._parse_query(query)
        if self.config.read_only and self.is_write_operation(command):
            raise PermissionError("Database 'redis' is configured as read-only.")

        started = time.perf_counter()
        result = self._get_client().execute_command(command, *args)
        elapsed = int((time.perf_counter() - started) * 1000)
        decoded = _decode_redis_value(result)
        rows = decoded if isinstance(decoded, list) else [decoded]
        return QueryExecutionResult(
            rows=[{"value": item} for item in rows],
            affected_rows=len(rows),
            execution_time_ms=elapsed,
            metadata={"family": self.family, "command": command},
        )

    async def get_schema(self) -> dict[str, Any]:
        client = self._get_client()
        keys = []
        for idx, key in enumerate(client.scan_iter(count=100)):
            if idx >= 50:
                break
            decoded_key = _decode_redis_value(key)
            key_type = _decode_redis_value(client.type(key))
            keys.append({"key": decoded_key, "type": key_type})
        return {
            "databaseType": self.config.db_type,
            "family": self.family,
            "keys": keys,
        }

    def is_write_operation(self, query: str) -> bool:
        return query.strip().lower() in self.write_commands
