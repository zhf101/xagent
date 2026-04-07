"""记忆后台治理 worker。

这个进程和 Web API 是分开的。
Web/API/Agent 侧只负责把 memory job 写进数据库，
真正的执行、重试、失败回收、定时维护，都由这个 worker 完成。

如果把整个记忆系统想成“生产者-消费者”模式：
- 生产者：ReAct / DAG / Web API
- 队列：memory_jobs 表
- 消费者：这个文件里的 MemoryGovernanceWorker
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import time
from typing import Any, Callable, Optional
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy.orm import Session, sessionmaker

from ..core.memory import MemoryJobRepository
from ..core.memory.job_executor_registry import MemoryJobExecutorRegistry
from ..web.logging_config import setup_logging
from ..web.models.database import init_db
from .maintenance_scheduler import MemoryMaintenanceScheduler

logger = logging.getLogger(__name__)

load_dotenv()


class MemoryGovernanceWorker:
    def __init__(
        self,
        *,
        session_factory: Optional[sessionmaker[Session] | Callable[[], Session]] = None,
        registry: Optional[MemoryJobExecutorRegistry] = None,
        scheduler: Optional[MemoryMaintenanceScheduler] = None,
        worker_id: Optional[str] = None,
        poll_interval_seconds: float = 5.0,
        lease_seconds: int = 300,
        job_types: Optional[list[str]] = None,
    ) -> None:
        # registry 决定“某种 job_type 该由谁执行”；
        # scheduler 决定“是否需要定时自动补充维护类 job”。
        self._session_factory = session_factory
        self._registry = registry or MemoryJobExecutorRegistry()
        self._scheduler = scheduler
        self.worker_id = worker_id or self._build_worker_id()
        self.poll_interval_seconds = poll_interval_seconds
        self.lease_seconds = lease_seconds
        self.job_types = job_types or self._registry.supported_job_types()

    def run_once(self) -> bool:
        """
        执行一个最小工作循环。

        流程是：
        1. 先让 scheduler 看看要不要补充维护任务。
        2. 再去数据库里 claim 一个可执行 job。
        3. 找到对应 executor 执行。
        4. 根据结果标记 success / fail / requeue。
        """
        if self._scheduler is not None:
            self._scheduler.tick()

        claimed_job_data: Optional[dict[str, Any]] = None
        # 注意这里会先“声明占有”任务，再释放数据库会话，
        # 后续真正执行业务逻辑时不长时间占着事务。
        with self._open_session() as session:
            repo = MemoryJobRepository(session)
            claimed_job = repo.claim_next_job(
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                job_types=self.job_types,
            )
            if claimed_job is not None:
                claimed_job_data = {
                    "id": int(claimed_job.id),
                    "job_type": str(claimed_job.job_type),
                    "payload_json": dict(claimed_job.payload_json or {}),
                    "source_user_id": claimed_job.source_user_id,
                    "source_session_id": claimed_job.source_session_id,
                    "source_project_id": claimed_job.source_project_id,
                    "source_task_id": claimed_job.source_task_id,
                }
            session.commit()

        if claimed_job_data is None:
            return False

        job_id = int(claimed_job_data["id"])
        job_type = str(claimed_job_data["job_type"])
        payload = dict(claimed_job_data["payload_json"])

        try:
            executor = self._registry.get_executor(job_type)
        except KeyError as exc:
            self._mark_failed(job_id, str(exc))
            logger.error("Memory job %s failed permanently: %s", job_id, exc)
            return True

        try:
            result = executor.execute(
                job_payload=payload,
                job_id=job_id,
                source_user_id=claimed_job_data["source_user_id"],
                source_session_id=claimed_job_data["source_session_id"],
                source_project_id=claimed_job_data["source_project_id"],
                source_task_id=claimed_job_data["source_task_id"],
            )
            self._mark_succeeded(job_id)
            logger.info("Memory job %s succeeded: %s", job_id, result)
        except Exception as exc:
            self._requeue(job_id, self._format_error(exc))
            logger.exception("Memory job %s execution failed", job_id)

        return True

    def run_forever(self) -> None:
        """持续消费队列；当没有可执行任务时按 poll_interval 休眠。"""
        logger.info(
            "Starting memory governance worker id=%s job_types=%s",
            self.worker_id,
            ",".join(self.job_types),
        )
        while True:
            processed = self.run_once()
            if not processed:
                time.sleep(self.poll_interval_seconds)

    def _mark_succeeded(self, job_id: int) -> None:
        with self._open_session() as session:
            repo = MemoryJobRepository(session)
            repo.mark_job_succeeded(job_id)
            session.commit()

    def _mark_failed(self, job_id: int, error: str) -> None:
        with self._open_session() as session:
            repo = MemoryJobRepository(session)
            repo.mark_job_failed(job_id, error=error[:4000])
            session.commit()

    def _requeue(self, job_id: int, error: str) -> None:
        with self._open_session() as session:
            repo = MemoryJobRepository(session)
            repo.requeue_job(job_id, error=error[:4000])
            session.commit()

    def _open_session(self):
        session_factory = self._session_factory or self._get_default_session_factory()
        if isinstance(session_factory, sessionmaker):
            return session_factory()
        return session_factory()

    @staticmethod
    def _get_default_session_factory():
        from ..web.models.database import get_session_local

        return get_session_local()

    @staticmethod
    def _build_worker_id() -> str:
        return f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"

    @staticmethod
    def _format_error(exc: Exception) -> str:
        return f"{type(exc).__name__}: {exc}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run xagent memory governance worker")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Sleep seconds when no job is available",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=300,
        help="Lease duration for claimed jobs",
    )
    parser.add_argument(
        "--job-type",
        action="append",
        dest="job_types",
        help="Optional job type filter, can be specified multiple times",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one available job and exit",
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Log level override",
    )
    return parser.parse_args()


def main() -> None:
    """命令行入口，可用于单次执行，也可常驻运行。"""
    args = parse_args()
    setup_logging(level=args.log_level if args.log_level else None)  # type: ignore[arg-type]
    init_db()
    scheduler = None
    if not args.job_types:
        scheduler = MemoryMaintenanceScheduler()

    worker = MemoryGovernanceWorker(
        scheduler=scheduler,
        poll_interval_seconds=args.poll_interval,
        lease_seconds=args.lease_seconds,
        job_types=args.job_types,
    )

    if args.once:
        worker.run_once()
        return

    worker.run_forever()


if __name__ == "__main__":
    main()
