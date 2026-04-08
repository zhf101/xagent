from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from .retry_config import DEFAULT_LLM_MAX_RETRIES


class VectorDBType(str, Enum):
    """Supported vector database backend types."""

    LANCEDB = "lancedb"
    WEAVIATE = "weaviate"
    WEAVIATE_SAAS = "weaviate_saas"
    CHROMADB = "chromadb"
    MILVUS = "milvus"
    QDRANT = "qdrant"
    PINECONE = "pinecone"
    PGVECTOR = "pgvector"
    ELASTICSEARCH = "elasticsearch"
    OPEN_SEARCH = "open_search"
    REDIS = "redis"
    FAISS = "faiss"
    TYPESENSE = "typesense"
    ZILLIZ = "zilliz"


class ModelConfig(BaseModel):
    """统一的模型配置基类。

    `max_retries` 是这次修复里最关键的控制项之一：
    - 它表示“单次模型调用内部”的最大重试次数。
    - 它不应该被当成外层 Agent 总循环次数使用。
    - 默认值现在收敛为 3，避免服务不可达时后台长时间挂起。
    """

    id: str
    model_name: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout: float = 180.0
    abilities: Optional[List[str]] = None
    description: Optional[str] = None
    max_retries: int = Field(default=DEFAULT_LLM_MAX_RETRIES)


class ChatModelConfig(ModelConfig):
    model_provider: str = "openai"
    default_temperature: Optional[float] = None
    default_max_tokens: Optional[int] = None
    thinking_mode: bool = False


class ImageModelConfig(ModelConfig):
    model_provider: str = "openai"
    default_temperature: Optional[float] = None
    default_max_tokens: Optional[int] = None


class EmbeddingModelConfig(ModelConfig):
    model_provider: str = "openai"
    dimension: Optional[int] = None
    instruct: Optional[str] = None


class RerankModelConfig(ModelConfig):
    model_provider: str = "openai"
    top_n: Optional[int] = None
    instruct: Optional[str] = None


class SpeechModelConfig(ModelConfig):
    """Configuration for speech models (ASR and TTS)."""

    model_provider: str = "openai"
    language: Optional[str] = None  # Default language code (e.g., 'zh', 'en')
    # TTS-specific configuration
    voice: Optional[str] = (
        None  # Default voice/speaker for TTS (e.g., 'female', 'male')
    )
    format: Optional[str] = None  # Audio format for TTS (e.g., 'mp3', 'wav', 'pcm')
    sample_rate: Optional[int] = None  # Sample rate for TTS in Hz (e.g., 24000, 48000)


class VectorDBConfig(ModelConfig):
    """Configuration for vector database backend (e.g. LanceDB, Weaviate).

    Note: When persisted via SQLAlchemyModelHub, the optional extra config dict
    is stored in the base model's ``abilities`` JSON column (semantic repurpose;
    for other categories ``abilities`` is Optional[List[str]]).
    """

    db_type: VectorDBType = VectorDBType.LANCEDB
    config: dict = Field(default_factory=dict)
