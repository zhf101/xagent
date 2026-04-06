"""Vanna 核心服务。"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "AskService",
    "IndexService",
    "KnowledgeBaseService",
    "PromptBuilder",
    "QueryService",
    "RetrievalService",
    "SchemaHarvestService",
    "SchemaAnnotationService",
    "SchemaSummaryService",
    "SqlAssetBindingService",
    "SqlAssetExecutionService",
    "SqlAssetInferenceService",
    "SqlAssetResolver",
    "SqlAssetService",
    "SqlTemplateCompiler",
    "TrainService",
]


_LAZY_IMPORTS = {
    "AskService": (".ask_service", "AskService"),
    "IndexService": (".index_service", "IndexService"),
    "KnowledgeBaseService": (".knowledge_base_service", "KnowledgeBaseService"),
    "PromptBuilder": (".prompt_builder", "PromptBuilder"),
    "QueryService": (".query_service", "QueryService"),
    "RetrievalService": (".retrieval_service", "RetrievalService"),
    "SchemaHarvestService": (".schema_harvest_service", "SchemaHarvestService"),
    "SchemaAnnotationService": (
        ".schema_annotation_service",
        "SchemaAnnotationService",
    ),
    "SchemaSummaryService": (".schema_summary_service", "SchemaSummaryService"),
    "SqlAssetBindingService": (
        ".sql_assets",
        "SqlAssetBindingService",
    ),
    "SqlAssetExecutionService": (
        ".sql_assets",
        "SqlAssetExecutionService",
    ),
    "SqlAssetInferenceService": (
        ".sql_assets",
        "SqlAssetInferenceService",
    ),
    "SqlAssetResolver": (".sql_assets", "SqlAssetResolver"),
    "SqlAssetService": (".sql_assets", "SqlAssetService"),
    "SqlTemplateCompiler": (".sql_assets", "SqlTemplateCompiler"),
    "TrainService": (".train_service", "TrainService"),
}


def __getattr__(name: str):
    module_name, attribute_name = _LAZY_IMPORTS.get(name, (None, None))
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
