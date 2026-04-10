"""Core configuration for xagent.

Provides unified configuration for all paths and directories that can be used
by both core and web modules without creating circular dependencies.

All paths support environment variable overrides for portable deployments.

Environment Variable Naming Convention:
    Most config variables use the XAGENT_* prefix for consistency.
    Exceptions (without XAGENT_ prefix) are kept for backward compatibility:
    - SANDBOX_*: Sandbox container configuration (predates this module)
    - BOXLITE_HOME_DIR: Boxlite sandbox home directory
    - DATABASE_URL: Standard database connection URL
    - LANCEDB_PATH: LanceDB database path

Future enhancement: Consider migrating to pydantic-settings for more robust
configuration management with validation, type safety, and better structure.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

logger = logging.getLogger(__name__)

# Environment variable names
UPLOADS_DIR = "XAGENT_UPLOADS_DIR"
WEB_DIR = "XAGENT_WEB_DIR"
EXTERNAL_UPLOAD_DIRS = "XAGENT_EXTERNAL_UPLOAD_DIRS"
EXTERNAL_SKILLS_LIBRARY_DIRS = "XAGENT_EXTERNAL_SKILLS_LIBRARY_DIRS"
STORAGE_ROOT = "XAGENT_STORAGE_ROOT"
SANDBOX_IMAGE = "SANDBOX_IMAGE"
LANCEDB_PATH = "LANCEDB_PATH"
DATABASE_URL = "DATABASE_URL"
VECTOR_BACKEND = "XAGENT_VECTOR_BACKEND"
VECTOR_PG_URL = "XAGENT_VECTOR_PG_URL"
VECTOR_PG_SCHEMA = "XAGENT_VECTOR_PG_SCHEMA"
VECTOR_PG_ENABLE_IVFFLAT = "XAGENT_VECTOR_PG_ENABLE_IVFFLAT"
VECTOR_MILVUS_URI = "XAGENT_VECTOR_MILVUS_URI"
VECTOR_MILVUS_TOKEN = "XAGENT_VECTOR_MILVUS_TOKEN"
VECTOR_MILVUS_DB_NAME = "XAGENT_VECTOR_MILVUS_DB_NAME"
SANDBOX_CPUS = "SANDBOX_CPUS"
SANDBOX_MEMORY = "SANDBOX_MEMORY"
SANDBOX_ENV = "SANDBOX_ENV"
SANDBOX_VOLUMES = "SANDBOX_VOLUMES"
BOXLITE_HOME_DIR = "BOXLITE_HOME_DIR"
DEFAULT_POSTGRES_URL = "postgresql://xagent:xagent_password@localhost:5432/xagent"


def _load_runtime_env_file() -> None:
    """在导入配置模块时统一加载 `.env`。

    这次修复的核心目标，是消除“不同启动方式读取到不同配置”的问题。
    之前只有 `python -m xagent.web` 这条入口会显式调用 `load_dotenv()`，
    但像下面这些常见开发路径都可能绕过它：
    - 直接 `uvicorn xagent.web.app:app`
    - 直接 import `xagent.config` / `xagent.web.app`
    - 各种脚本、REPL、pytest、一次性诊断命令

    因此把 `.env` 加载下沉到 `config.py` 才是更稳妥的收口点：
    - 只要代码开始读取配置，就先尽力把 `.env` 载入
    - 仍保持“进程环境变量优先于 `.env`”的原则，不覆盖外部显式传入值

    查找顺序刻意设计成两层：
    1. 先按当前工作目录向上搜索 `.env`
       适合本地开发时在仓库根目录执行命令，也兼容从子目录进入项目
    2. 再回退到当前源码仓库根目录下的 `.env`
       适合 `src/` 布局下通过 `PYTHONPATH=src` 或 editable install 运行时，
       即使调用方 cwd 偏移，也还能回到这份源码自己的根目录找配置

    两个候选路径会去重，并且统一使用 `override=False`，
    避免把已存在的系统环境变量偷偷覆盖掉。
    """
    candidate_paths: list[Path] = []

    cwd_env = find_dotenv(filename=".env", usecwd=True)
    if cwd_env:
        candidate_paths.append(Path(cwd_env).resolve())

    repo_root_env = Path(__file__).resolve().parents[2] / ".env"
    if repo_root_env.exists():
        candidate_paths.append(repo_root_env.resolve())

    loaded_paths: set[Path] = set()
    for env_path in candidate_paths:
        if env_path in loaded_paths:
            continue
        load_dotenv(env_path, override=False)
        loaded_paths.add(env_path)


_load_runtime_env_file()


def get_web_dir() -> Path:
    """Get the web directory path.

    Priority:
    1. XAGENT_WEB_DIR environment variable
    2. Default to src/xagent/web relative to this file

    Returns:
        Path object for web directory
    """
    env_dir = os.getenv(WEB_DIR)
    if env_dir:
        return Path(env_dir)

    # Default: src/xagent/web relative to this file
    # This file is at: src/xagent/config.py
    # Web dir is at: src/xagent/web/
    return Path(__file__).parent / "web"


def get_uploads_dir() -> Path:
    """Get the uploads directory path.

    Priority:
    1. XAGENT_UPLOADS_DIR environment variable
    2. Default to WEB_DIR/uploads for backward compatibility

    Returns:
        Path object for uploads directory
    """
    env_dir = os.getenv(UPLOADS_DIR)
    if env_dir:
        return Path(env_dir)

    # Default: web/uploads
    web_dir = get_web_dir()
    return web_dir / "uploads"


def get_external_upload_dirs() -> list[Path]:
    """Get external upload directories from environment variable.

    The XAGENT_EXTERNAL_UPLOAD_DIRS environment variable should contain
    a comma-separated list of directory paths.

    Example: /path/to/uploads1,/path/to/uploads2

    Only directories that exist are included in the result.

    Returns:
        List of Path objects for existing external directories
    """
    env_dirs = os.getenv(EXTERNAL_UPLOAD_DIRS, "")
    if not env_dirs:
        return []

    result = []
    for dir_path in env_dirs.split(","):
        dir_path = dir_path.strip()
        if dir_path:
            path = Path(dir_path)
            if path.is_dir():
                result.append(path)
            else:
                logger.warning(
                    "External upload directory does not exist or is not a directory: %r",
                    path,
                )

    return result


def get_external_skills_dirs() -> list[Path]:
    """Get external skills library directories from environment variable.

    The XAGENT_EXTERNAL_SKILLS_LIBRARY_DIRS environment variable should contain
    a comma-separated list of directory paths. Supports ~ expansion and environment
    variable expansion in paths.

    Example: ~/my-skills,/opt/skills,$PROJECT_DIR/skills

    Note: Unlike get_external_upload_dirs(), this includes all configured paths
    even if they don't exist yet. This allows users to configure skills directories
    before creating them.

    Returns:
        List of Path objects for external skills directories
    """
    env_dirs = os.getenv(EXTERNAL_SKILLS_LIBRARY_DIRS, "")
    if not env_dirs:
        return []

    result = []
    for dir_path in env_dirs.split(","):
        dir_path = dir_path.strip()
        if not dir_path:
            continue

        # Check for URL-like paths before path expansion
        if "://" in dir_path:
            logger.warning(f"Skipping non-local path (not supported yet): {dir_path}")
            continue

        # Expand environment variables and user home directory
        expanded_path = os.path.expanduser(os.path.expandvars(dir_path))
        path = Path(expanded_path)

        result.append(path)

    return result


def get_storage_root() -> Path:
    """Get the storage root directory path.

    Priority:
    1. XAGENT_STORAGE_ROOT environment variable
    2. Default to ~/.xagent

    Returns:
        Path object for storage root directory
    """
    env_dir = os.getenv(STORAGE_ROOT)
    if env_dir:
        return Path(env_dir)

    # Default: ~/.xagent
    return Path.home() / ".xagent"


def get_sandbox_image() -> str:
    """Get the default sandbox image name.

    Priority:
    1. SANDBOX_IMAGE environment variable
    2. Default to xprobe/xagent-sandbox:latest

    Returns:
        Sandbox image name
    """
    return os.getenv(SANDBOX_IMAGE, "xprobe/xagent-sandbox:latest")


def get_lancedb_path() -> Path:
    """Get the LanceDB database path.

    Priority:
    1. LANCEDB_PATH environment variable
    2. Default to ./data/lancedb (relative to cwd)

    .. warning::
        Default to ``./data/lancedb``, which is **relative** to cwd, **NOT**
        relative to ``storage_root``. This behavior is kept for backward
        compatibility but may change in the future (see proposal #246).

    Returns:
        Path object for LanceDB directory
    """
    env_path = os.getenv(LANCEDB_PATH)
    if env_path:
        return Path(env_path)

    # Default: ./data/lancedb
    return Path("data/lancedb")


def get_default_sqlite_db_path() -> str:
    """返回历史 SQLite 默认文件路径。

    这个 helper 暂时保留，原因只有两个：
    1. 当前测试集中还有少量 sqlite 夹具直接复用它
    2. 旧脚本或诊断代码可能仍引用这个名字

    但从当前项目主线约束看，业务运行时已经不再把 SQLite 当默认主库。
    后续如果连测试也一起切到 PostgreSQL，可以再统一移除。

    Returns:
        Path string for SQLite database file in storage root
    """
    # The original implementation in manager.py returned str
    # So we need to convert it to str here
    storage_root = get_storage_root()
    return str(storage_root / "xagent.db")


def get_default_postgres_url() -> str:
    """返回本地开发环境默认 PostgreSQL 连接串。

    这里把默认值显式收口成一处，原因是现在项目已经转向 PostgreSQL-first：
    - 没显式传 `DATABASE_URL` 时，不应该再偷偷回落到 SQLite
    - Docker Compose、README、本地开发脚本都应该围绕同一条默认连接串对齐
    """
    return DEFAULT_POSTGRES_URL


def get_database_url() -> str:
    """Get the database URL.

    Priority:
    1. DATABASE_URL environment variable (full connection string)
    2. Default to local PostgreSQL development instance

    Returns:
        Database connection string
    """
    database_url = os.getenv(DATABASE_URL)
    if database_url is not None:
        return database_url

    # 项目主线已切换为 PostgreSQL-first，未配置时直接回到本地 pgvector/pg17
    # 对应的默认开发连接，避免再次出现“忘配 DATABASE_URL 就静默落到 SQLite”的隐患。
    return get_default_postgres_url()


def get_vector_backend() -> str:
    """获取向量后端类型。

    这里单独抽一层配置，而不是复用 `DATABASE_URL` 做隐式推断，
    原因是主业务库和向量库虽然都可能指向 PostgreSQL，
    但运维语义、故障排查路径和后续扩展能力并不相同。

    Returns:
        `lancedb`、`pgvector` 或 `milvus`

    Raises:
        ValueError: 当环境变量值不在支持列表中时抛出
    """
    raw_value = os.getenv(VECTOR_BACKEND, "lancedb")
    normalized = raw_value.strip().lower()
    if not normalized:
        return "lancedb"
    if normalized not in {"lancedb", "pgvector", "milvus"}:
        raise ValueError(
            f"Invalid {VECTOR_BACKEND} value: {raw_value}. "
            "Expected one of: lancedb, pgvector, milvus"
        )
    return normalized


def get_vector_pg_url() -> str:
    """获取 pgvector 后端连接串。

    约定上优先读取 `XAGENT_VECTOR_PG_URL`，
    未配置时回退到主业务库 `DATABASE_URL`。
    这样可以支持“业务表和向量表共用一个 PostgreSQL 实例”的部署方式，
    也允许未来拆成独立向量库而不影响现有主库配置。
    """
    vector_url = os.getenv(VECTOR_PG_URL)
    if vector_url is not None and vector_url.strip():
        return vector_url.strip()
    return get_database_url()


def get_vector_pg_schema() -> str:
    """获取 pgvector 逻辑 schema 名称。"""
    raw_schema = os.getenv(VECTOR_PG_SCHEMA, "xagent_vector").strip()
    if not raw_schema:
        return "xagent_vector"
    return raw_schema


def get_vector_pg_enable_ivfflat() -> bool:
    """获取 pgvector 是否允许优先创建 IVFFLAT 索引。

    当前实现里这个开关只影响 pgvector 后端索引策略，
    不影响 LanceDB、业务主库或 ORM 模型初始化。
    """
    raw_value = os.getenv(VECTOR_PG_ENABLE_IVFFLAT, "true").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def get_vector_milvus_uri() -> str:
    """获取 Milvus 连接地址。"""
    uri = os.getenv(VECTOR_MILVUS_URI) or os.getenv("MILVUS_URI")
    normalized = str(uri or "").strip()
    if not normalized:
        raise ValueError(
            "Milvus backend requires XAGENT_VECTOR_MILVUS_URI or MILVUS_URI"
        )
    return normalized


def get_vector_milvus_token() -> str | None:
    """获取 Milvus token。"""
    token = os.getenv(VECTOR_MILVUS_TOKEN)
    if token is None:
        token = os.getenv("MILVUS_TOKEN")
    normalized = str(token or "").strip()
    return normalized or None


def get_vector_milvus_db_name() -> str | None:
    """获取 Milvus 逻辑数据库名。"""
    db_name = os.getenv(VECTOR_MILVUS_DB_NAME)
    if db_name is None:
        db_name = os.getenv("MILVUS_DB_NAME")
    normalized = str(db_name or "").strip()
    return normalized or None


def get_sandbox_cpus() -> int | None:
    """Get the CPU count for sandbox containers.

    Returns:
        CPU count from SANDBOX_CPUS env var, or None
    """
    env_str = os.getenv(SANDBOX_CPUS)
    if env_str:
        try:
            return int(env_str)
        except ValueError:
            logger.warning(f"Invalid {SANDBOX_CPUS} value: {env_str}")
    return None


def get_sandbox_memory() -> int | None:
    """Get the memory limit for sandbox containers (in MB).

    Returns:
        Memory value from SANDBOX_MEMORY env var, or None
    """
    env_str = os.getenv(SANDBOX_MEMORY)
    if env_str:
        try:
            return int(env_str)
        except ValueError:
            logger.warning(f"Invalid {SANDBOX_MEMORY} value: {env_str}")
    return None


def get_sandbox_env() -> dict[str, str]:
    """Get the environment variables for sandbox containers.

    Format: KEY1=value1;KEY2=value2

    Returns:
        Dictionary of environment variables
    """
    env_str = os.getenv(SANDBOX_ENV, "").strip()
    if not env_str:
        return {}

    env = {}
    for pair in env_str.split(";"):
        try:
            key, value = pair.strip().split("=", 1)
        except ValueError:
            logger.warning("Invalid sandbox env config: must be in KEY=value format")
            continue

        key = key.strip()
        value = value.strip()
        if key and value:
            env[key] = value
        elif not key:
            logger.warning("Environment variable has empty key")
        elif not value:
            logger.warning(f"Environment variable {key!r} has empty value")

    return env


def get_sandbox_volumes() -> list[tuple[str, str, str]]:
    """Get the volume mappings for sandbox containers.

    Format: src:dst[:mode];src2:dst2[:mode2]
    - src: source path on host (expanded ~ and env vars)
    - dst: destination path in container
    - mode: ro or rw (default: ro)

    Returns:
        List of (src, dst, mode) tuples
    """
    env_str = os.getenv(SANDBOX_VOLUMES, "").strip()
    if not env_str:
        return []

    volumes = []
    for item in env_str.split(";"):
        item = item.strip()
        if not item:
            continue

        parts = item.split(":", 2)
        if len(parts) < 2:
            logger.warning(f"Invalid sandbox volume config: {item}")
            continue

        src = os.path.expanduser(os.path.expandvars(parts[0].strip()))
        dst = parts[1].strip()
        if not src or not dst:
            logger.warning(f"Invalid sandbox volume: {item}")
            continue

        # Normalize paths to resolve any relative components
        src = os.path.abspath(src)
        mode = parts[2].strip().lower() if len(parts) > 2 else "ro"
        if mode not in ("ro", "rw"):
            logger.warning(f"Invalid sandbox volume mode: {item}, using 'ro'")
            mode = "ro"

        volumes.append((src, dst, mode))

    return volumes


def get_boxlite_home_dir() -> Path | None:
    """Get the BoxLite home directory path.

    Returns:
        Path from BOXLITE_HOME_DIR env var, or None
    """
    env_str = os.getenv(BOXLITE_HOME_DIR)
    if env_str:
        return Path(env_str)
    return None
