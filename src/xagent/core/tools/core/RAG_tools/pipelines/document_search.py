"""Document search pipeline orchestrating multiple retrieval strategies."""

from __future__ import annotations

import logging
import numbers
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union, cast

import requests

from xagent.core.model.embedding.base import BaseEmbedding
from xagent.core.model.rerank.base import BaseRerank

from ..core.exceptions import (
    DocumentValidationError,
    RagCoreException,
    VectorValidationError,
)
from ..core.schemas import (
    DenseSearchResponse,
    HybridSearchResponse,
    SearchConfig,
    SearchPipelineResult,
    SearchResult,
    SearchType,
    SparseSearchResponse,
)
from ..progress import ProgressManager, ProgressTracker
from ..retrieval.search_dense import search_dense
from ..retrieval.search_hybrid import _rrf_fusion, search_hybrid
from ..retrieval.search_sparse import search_sparse
from ..utils.config_utils import coerce_search_config
from ..utils.model_resolver import resolve_embedding_adapter, resolve_rerank_adapter

logger = logging.getLogger(__name__)


def _resolve_dashscope_rerank(cfg: Optional[SearchConfig] = None) -> Optional[BaseRerank]:
    """Resolve rerank adapter with current OpenAI-compatible config and legacy env flags."""
    rerank_enabled = os.getenv("DASHSCOPE_RERANK_ENABLED", "true").lower() in (
        "true",
        "1",
        "yes",
    )
    if not rerank_enabled:
        return None

    # Legacy DashScope mode should not silently fall back to unrelated OPENAI_API_KEY.
    if (
        not (cfg and cfg.rerank_model_id)
        and os.getenv("DASHSCOPE_RERANK_MODEL")
        and not (
            os.getenv("DASHSCOPE_RERANK_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        )
    ):
        return None

    try:
        model_id = cfg.rerank_model_id if cfg and cfg.rerank_model_id else None
        _, rerank_adapter = resolve_rerank_adapter(
            model_id=model_id,
            api_key=None,
            base_url=None,
            timeout_sec=None,
            top_n=cfg.rerank_top_k if cfg else None,
        )
        if hasattr(rerank_adapter, "_inner"):
            inner = rerank_adapter._inner
            if hasattr(inner, "_rerank_model"):
                return inner._rerank_model
        return rerank_adapter
    except (RagCoreException, ValueError, TypeError, ImportError) as exc:
        logger.warning("Failed to load rerank adapter: %s", exc)
        return None


def _encode_query_vector(adapter: BaseEmbedding, query_text: str) -> List[float]:
    """Encode query text into a single vector using embedding adapter."""
    try:
        raw_vector = adapter.encode(query_text)
    except Exception as exc:
        raise VectorValidationError(
            f"Embedding adapter failed to encode query: {exc}"
        ) from exc

    if not isinstance(raw_vector, list):
        raise VectorValidationError("Embedding provider returned invalid response type")

    if not raw_vector:
        raise VectorValidationError("Embedding provider returned empty vector")

    first_item = raw_vector[0]
    if isinstance(first_item, list):
        if len(raw_vector) != 1:
            raise VectorValidationError(
                "Embedding provider returned multiple vectors for single query"
            )
        vector = cast(List[float], first_item)
    else:
        vector = cast(List[float], raw_vector)

    if not all(isinstance(value, numbers.Number) for value in vector):
        raise VectorValidationError("Embedding vector contains non-numeric values")

    return [float(value) for value in vector]


def _serialize_warnings(warnings: Sequence) -> List[str]:
    """Convert warning objects to human-readable strings."""
    serialized: List[str] = []
    for warning in warnings:
        code = getattr(warning, "code", None)
        message = getattr(warning, "message", "")
        if code:
            serialized.append(f"{code}: {message}")
        else:
            serialized.append(str(message))
    return serialized


def _map_reranked_texts_to_results(
    reranked_texts: Sequence[str], original_results: List[SearchResult]
) -> List[SearchResult]:
    """Map reranked texts back to SearchResult objects preserving order."""
    text_to_results: Dict[str, List[SearchResult]] = {}
    for result in original_results:
        text_to_results.setdefault(result.text, []).append(result)

    ordered_results: List[SearchResult] = []
    for text in reranked_texts:
        queue = text_to_results.get(text)
        if queue:
            ordered_results.append(queue.pop(0))

    for queue in text_to_results.values():
        ordered_results.extend(queue)

    return ordered_results


def _apply_rerank_top_k_limit(
    results: List[SearchResult], rerank_top_k: Optional[int]
) -> List[SearchResult]:
    """Apply rerank_top_k limit if specified."""
    if rerank_top_k is not None and rerank_top_k > 0:
        return results[:rerank_top_k]
    return results


def _try_dashscope_rerank(
    results: List[SearchResult],
    query_text: str,
    cfg: SearchConfig,
    warnings: List[str],
) -> Optional[Tuple[List[SearchResult], bool, List[str]]]:
    """Try to rerank results using the configured rerank adapter."""
    rerank_adapter = _resolve_dashscope_rerank(cfg)
    if rerank_adapter is None:
        return None

    documents = [result.text for result in results]
    if not documents:
        return None

    try:
        reranked_texts = rerank_adapter.compress(documents, query_text)
        ordered_results = _map_reranked_texts_to_results(reranked_texts, results)

        if not ordered_results:
            warnings.append(
                "Rerank returned no recognizable documents; falling back to RRF."
            )
            return None

        ordered_results = _apply_rerank_top_k_limit(ordered_results, cfg.rerank_top_k)
        return ordered_results, True, warnings
    except (
        requests.exceptions.RequestException,
        requests.exceptions.HTTPError,
        KeyError,
        ValueError,
        TypeError,
    ) as exc:
        logger.warning("DashScope rerank failed: %s, falling back to RRF", exc)
        warnings.append(f"DashScope rerank failed: {exc}, using RRF fallback")
        return None


def _try_lancedb_rrf_fallback(
    results: List[SearchResult],
    cfg: SearchConfig,
    warnings: List[str],
) -> Optional[Tuple[List[SearchResult], bool, List[str]]]:
    """Try to rerank results using LanceDB RRF fusion as fallback."""
    has_vector_scores = any(r.vector_score is not None for r in results)
    has_fts_scores = any(r.fts_score is not None for r in results)
    if not (has_vector_scores and has_fts_scores):
        warnings.append(
            "Cannot apply RRF fallback: missing original vector/FTS scores. "
            "Ensure hybrid search is used to populate vector_score, fts_score, vector_rank, fts_rank."
        )
        return None

    rrf_k = int(os.getenv("DASHSCOPE_RERANK_RRF_K", "60"))
    vector_results: List[SearchResult] = []
    fts_results: List[SearchResult] = []

    for result in results:
        if result.vector_score is not None:
            vector_results.append(result)
        if result.fts_score is not None:
            fts_results.append(result)

    vector_results.sort(key=lambda r: r.vector_rank or 999999)
    fts_results.sort(key=lambda r: r.fts_rank or 999999)

    try:
        reranked_results = _rrf_fusion([vector_results, fts_results], k=rrf_k)
        reranked_results = _apply_rerank_top_k_limit(reranked_results, cfg.rerank_top_k)
        logger.info("Applied LanceDB RRF rerank fallback")
        return reranked_results, True, warnings
    except (AttributeError, TypeError, ValueError, ZeroDivisionError) as exc:
        logger.warning("LanceDB RRF rerank failed: %s", exc)
        warnings.append(f"LanceDB RRF rerank failed: {exc}")
        return None


def _apply_rerank_if_needed(
    results: List[SearchResult],
    query_text: str,
    cfg: SearchConfig,
) -> Tuple[List[SearchResult], bool, List[str]]:
    """Optionally rerank search results using adapter -> LanceDB RRF fallback."""
    warnings: List[str] = []
    if not results:
        return results, False, warnings

    if not cfg.rerank_model_id and cfg.rerank_top_k is None:
        fallback_enabled = os.getenv(
            "DASHSCOPE_RERANK_FALLBACK_TO_LANCEDB", "true"
        ).lower() in ("true", "1", "yes")
        rerank_available = _resolve_dashscope_rerank(cfg) is not None
        if not rerank_available and not fallback_enabled:
            return results, False, warnings

    rerank_result = _try_dashscope_rerank(results, query_text, cfg, warnings)
    if rerank_result:
        return rerank_result

    fallback_to_lancedb = os.getenv(
        "DASHSCOPE_RERANK_FALLBACK_TO_LANCEDB", "true"
    ).lower() in ("true", "1", "yes")
    if fallback_to_lancedb:
        rrf_result = _try_lancedb_rrf_fallback(results, cfg, warnings)
        if rrf_result:
            return rrf_result

    return results, False, warnings


def _limit_results(results: List[SearchResult], cfg: SearchConfig) -> List[SearchResult]:
    """Limit results according to top_k configuration."""
    final_limit = cfg.top_k
    if final_limit <= 0:
        return results
    return results[:final_limit]


def _build_pipeline_result(
    *,
    status: str,
    search_type: SearchType,
    results: List[SearchResult],
    warnings: List[str],
    message: str,
    used_rerank: bool,
    cfg: SearchConfig,
) -> SearchPipelineResult:
    """Build pipeline response object."""
    limited_results = _limit_results(results, cfg)
    return SearchPipelineResult(
        status=status,
        search_type=search_type,
        results=limited_results,
        result_count=len(limited_results),
        warnings=warnings,
        message=message,
        used_rerank=used_rerank,
    )


def _execute_sparse_search(
    collection: str,
    query_text: str,
    cfg: SearchConfig,
    model_tag: str,
    user_id: Optional[int] = None,
    is_admin: bool = False,
) -> Tuple[List[SearchResult], str, List[str], str]:
    """Execute sparse search and return components for pipeline result."""
    fetch_top_k = max(cfg.top_k, cfg.rerank_top_k or 0)
    sparse_response: SparseSearchResponse = search_sparse(
        collection=collection,
        model_tag=model_tag,
        query_text=query_text,
        top_k=fetch_top_k or cfg.top_k,
        filters=cfg.filters,
        readonly=cfg.readonly,
        user_id=user_id,
        is_admin=is_admin,
    )
    warnings = _serialize_warnings(sparse_response.warnings)
    status = sparse_response.status or "success"
    message = (
        "Sparse search completed successfully"
        if sparse_response.status == "success"
        else "Sparse search completed with warnings"
    )
    return list(sparse_response.results), status, warnings, message


SearchConfigInput = Union[SearchConfig, Mapping[str, Any]]


def _handle_search_error(
    exc: Exception,
    current_step: str,
    search_type: SearchType,
    warnings: List[str],
) -> SearchPipelineResult:
    """Unify error handling for the search pipeline."""
    logger.exception(
        "Document search pipeline failed at step '%s': %s", current_step, exc
    )
    return SearchPipelineResult(
        status="error",
        search_type=search_type,
        results=[],
        result_count=0,
        warnings=warnings + [f"{current_step}: {exc}"],
        message=f"{current_step} failed: {exc}",
        used_rerank=False,
    )


def search_documents(
    collection: str,
    query_text: str,
    *,
    config: Optional[SearchConfig] = None,
    progress_manager: Optional[ProgressManager] = None,
    user_id: Optional[int] = None,
    is_admin: bool = False,
) -> SearchPipelineResult:
    """Execute the document search pipeline end-to-end.

    The pipeline coordinates sparse, dense, or hybrid retrieval strategies.

    Args:
        collection: Logical collection to search within.
        query_text: Natural-language query or keyword phrase.
        config: Optional search configuration override.
        progress_manager: Optional progress manager for tracking.
        user_id: Optional user ID for ownership tracking.
        is_admin: Whether the user has admin privileges.

    Returns:
        SearchPipelineResult: Structured result containing status, results, and warnings.

    Raises:
        DocumentValidationError: Missing/malformed inputs.
        EmbeddingAdapterError: Embedding model cannot be loaded.
        VectorValidationError: Query embedding fails.
    """
    cfg = (
        config
        if isinstance(config, SearchConfig)
        else coerce_search_config(config or {})
    )

    if not collection or not isinstance(collection, str):
        raise DocumentValidationError("collection must be a non-empty string")
    if not query_text or not isinstance(query_text, str):
        raise DocumentValidationError("query_text must be a non-empty string")

    if progress_manager is None:
        from ..progress import get_progress_manager as _get_pm
        progress_manager = _get_pm()

    requested_type = cfg.search_type
    fetch_top_k = max(cfg.top_k, cfg.rerank_top_k or 0)
    warnings: List[str] = []

    # Get collection's bound embedding model
    from ..management.collection_manager import resolve_effective_embedding_model_sync

    try:
        model_id = resolve_effective_embedding_model_sync(
            collection, cfg.embedding_model_id
        )
        cfg = cfg.model_copy(update={"embedding_model_id": model_id})
        logger.info(
            "Using resolved embedding model '%s' for collection '%s'",
            model_id,
            collection,
        )
    except ValueError as e:
        if "not found" in str(e):
            raise DocumentValidationError(f"Collection '{collection}' not found")
        raise

    current_step = "initialize"
    task_id = f"search_{collection}_{hash(query_text) % 10000:04d}"
    progress_tracker = ProgressTracker(progress_manager, task_id)
    progress_manager.create_task(
        task_type="search",
        task_id=task_id,
        user_id=user_id,
        metadata={
            "collection": collection,
            "query": query_text[:100],
        },
    )

    try:
        embedding_config, embedding_adapter = resolve_embedding_adapter(
            cfg.embedding_model_id,
            api_key=None,
            base_url=None,
            timeout_sec=None,
        )
        model_tag = embedding_config.model_name
        current_step = "post_resolve_embedding"
        actual_type = requested_type
        results: List[SearchResult] = []
        status = "success"
        message = "Search completed successfully"
        used_rerank = False

        if requested_type == SearchType.SPARSE:
            current_step = "search_sparse"
            results, status, sparse_warnings, message = _execute_sparse_search(
                collection, query_text, cfg, model_tag, user_id, is_admin
            )
            warnings.extend(sparse_warnings)
        else:
            try:
                current_step = "encode_query_vector"
                query_vector = _encode_query_vector(embedding_adapter, query_text)
            except VectorValidationError:
                if requested_type == SearchType.HYBRID and cfg.fallback_to_sparse:
                    current_step = "search_sparse_fallback"
                    logger.warning(
                        "Hybrid search embedding failed; falling back to sparse search."
                    )
                    warnings.append("Hybrid search embedding failed; fallback to sparse.")
                    results, status, sparse_warnings, message = _execute_sparse_search(
                        collection, query_text, cfg, model_tag
                    )
                    warnings.extend(sparse_warnings)
                    actual_type = SearchType.SPARSE
                else:
                    raise
            else:
                if requested_type == SearchType.DENSE:
                    dense_response: DenseSearchResponse = search_dense(
                        collection=collection,
                        model_tag=model_tag,
                        query_vector=query_vector,
                        top_k=fetch_top_k,
                        filters=cfg.filters,
                        readonly=cfg.readonly,
                        nprobes=cfg.nprobes,
                        refine_factor=cfg.refine_factor,
                        user_id=user_id,
                        is_admin=is_admin,
                    )
                    warnings.extend(_serialize_warnings(dense_response.warnings))
                    results = list(dense_response.results)
                    status = dense_response.status or "success"
                    message = dense_response.index_advice or "Dense search completed successfully"
                else:  # HYBRID
                    try:
                        hybrid_response: HybridSearchResponse = search_hybrid(
                            collection=collection,
                            model_tag=model_tag,
                            query_text=query_text,
                            query_vector=query_vector,
                            top_k=fetch_top_k,
                            filters=cfg.filters,
                            fusion_config=cfg.fusion_config,
                            readonly=cfg.readonly,
                            nprobes=cfg.nprobes,
                            refine_factor=cfg.refine_factor,
                            user_id=user_id,
                            is_admin=is_admin,
                        )
                    except (RagCoreException, ValueError, TypeError) as exc:
                        if cfg.fallback_to_sparse:
                            logger.warning(
                                "Hybrid search failed (%s); falling back to sparse search",
                                exc,
                            )
                            warnings.append(f"Hybrid search failed and fell back to sparse: {exc}")
                            results, status, sparse_warnings, message = _execute_sparse_search(
                                collection, query_text, cfg, model_tag
                            )
                            warnings.extend(sparse_warnings)
                            actual_type = SearchType.SPARSE
                        else:
                            current_step = "search_hybrid"
                            raise
                    else:
                        warnings.extend(_serialize_warnings(hybrid_response.warnings))
                        results = list(hybrid_response.results)
                        status = hybrid_response.status or "success"
                        message = "Hybrid search completed successfully"

        current_step = "apply_rerank"
        results, used_rerank, rerank_warnings = _apply_rerank_if_needed(
            results, query_text, cfg
        )
        warnings.extend(rerank_warnings)

        return _build_pipeline_result(
            status=status,
            search_type=actual_type,
            results=results,
            warnings=warnings,
            message=message,
            used_rerank=used_rerank,
            cfg=cfg,
        )

    except (RagCoreException, Exception) as exc:
        return _handle_search_error(
            exc=exc,
            current_step=current_step,
            search_type=cfg.search_type,
            warnings=warnings,
        )


def run_document_search(
    collection: str,
    query_text: str,
    *,
    config: Optional[SearchConfigInput] = None,
    progress_manager: Optional[ProgressManager] = None,
    user_id: Optional[int] = None,
    is_admin: bool = False,
) -> SearchPipelineResult:
    """Public entrypoint for LangGraph-compatible tooling."""
    cfg = coerce_search_config(config if config is not None else {})
    return search_documents(
        collection,
        query_text,
        config=cfg,
        progress_manager=progress_manager,
        user_id=user_id,
        is_admin=is_admin,
    )
