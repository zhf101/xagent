"use client"

export type VannaKnowledgeBaseStatus = "draft" | "active" | "archived"
export type VannaSchemaTableStatus = "active" | "stale" | "archived"
export type VannaTrainingLifecycleStatus = "candidate" | "published" | "archived"
export type VannaTrainingEntryType =
  | "schema_summary"
  | "question_sql"
  | "documentation"
export type VannaHarvestJobStatus = "running" | "completed" | "failed"
export type VannaAskExecutionStatus =
  | "generated"
  | "executed"
  | "failed"
  | "waiting_approval"
export type VannaSqlAssetStatus = "draft" | "published" | "archived"

export interface Text2SqlDatabaseRecord {
  id: number
  name: string
  system_short: string
  database_name?: string | null
  env: string
  type: string
  url: string
  read_only: boolean
  status: string
  table_count?: number | null
  last_connected_at?: string | null
  error_message?: string | null
  created_at: string
  updated_at: string
}

export interface VannaKnowledgeBaseRecord {
  id: number
  kb_code: string
  name: string
  description?: string | null
  owner_user_id: number
  owner_user_name?: string | null
  datasource_id: number
  datasource_name?: string | null
  system_short: string
  database_name?: string | null
  env: string
  db_type?: string | null
  dialect?: string | null
  status: VannaKnowledgeBaseStatus
  default_top_k_sql?: number | null
  default_top_k_schema?: number | null
  default_top_k_doc?: number | null
  embedding_model?: string | null
  llm_model?: string | null
  last_train_at?: string | null
  last_ask_at?: string | null
  created_at: string
  updated_at: string
}

export interface VannaSchemaHarvestJobRecord {
  id: number
  kb_id: number
  datasource_id: number
  system_short: string
  env: string
  status: VannaHarvestJobStatus | string
  harvest_scope: string
  schema_names_json: string[]
  table_names_json: string[]
  request_payload_json: Record<string, unknown>
  result_payload_json: Record<string, unknown>
  error_message?: string | null
  create_user_id: number
  create_user_name?: string | null
  started_at?: string | null
  completed_at?: string | null
  created_at: string
  updated_at: string
}

export interface VannaSchemaTableRecord {
  id: number
  kb_id: number
  datasource_id: number
  harvest_job_id: number
  system_short: string
  env: string
  catalog_name?: string | null
  schema_name?: string | null
  table_name: string
  table_type?: string | null
  table_comment?: string | null
  table_ddl?: string | null
  primary_key_json: string[]
  foreign_keys_json: Array<Record<string, unknown>>
  indexes_json: Array<Record<string, unknown>>
  constraints_json: Array<Record<string, unknown>>
  row_count_estimate?: number | null
  content_hash?: string | null
  status: VannaSchemaTableStatus | string
  created_at: string
  updated_at: string
}

export interface VannaSchemaColumnRecord {
  id: number
  table_id: number
  kb_id: number
  datasource_id: number
  system_short: string
  env: string
  schema_name?: string | null
  table_name: string
  column_name: string
  ordinal_position?: number | null
  data_type?: string | null
  udt_name?: string | null
  is_nullable?: boolean | null
  default_raw?: string | null
  default_kind?: string | null
  column_comment?: string | null
  is_primary_key?: boolean | null
  is_foreign_key?: boolean | null
  foreign_table_name?: string | null
  foreign_column_name?: string | null
  is_generated?: boolean | null
  generation_expression?: string | null
  value_source_kind?: string | null
  allowed_values_json: string[]
  sample_values_json: string[]
  stats_json: Record<string, unknown>
  semantic_tags_json: string[]
  content_hash?: string | null
  business_description?: string | null
  comment_override?: string | null
  default_value_override?: string | null
  allowed_values_override_json: string[]
  sample_values_override_json: string[]
  effective_default_raw?: string | null
  effective_column_comment?: string | null
  effective_allowed_values_json: string[]
  effective_sample_values_json: string[]
  annotation?: {
    id: number
    kb_id: number
    datasource_id: number
    schema_name?: string | null
    table_name: string
    column_name: string
    business_description?: string | null
    comment_override?: string | null
    default_value_override?: string | null
    allowed_values_override_json: string[]
    sample_values_override_json: string[]
    update_source: string
    create_user_id: number
    create_user_name?: string | null
    updated_by_user_id: number
    updated_by_user_name?: string | null
    created_at?: string | null
    updated_at?: string | null
  } | null
  created_at: string
  updated_at: string
}

export interface VannaTrainingEntryRecord {
  id: number
  kb_id: number
  datasource_id: number
  system_short: string
  env: string
  entry_code: string
  entry_type: VannaTrainingEntryType | string
  source_kind?: string | null
  source_ref?: string | null
  lifecycle_status: VannaTrainingLifecycleStatus | string
  quality_status?: string | null
  title?: string | null
  question_text?: string | null
  sql_text?: string | null
  sql_explanation?: string | null
  doc_text?: string | null
  schema_name?: string | null
  table_name?: string | null
  business_domain?: string | null
  system_name?: string | null
  subject_area?: string | null
  statement_kind?: string | null
  tables_read_json: string[]
  columns_read_json: string[]
  output_fields_json: string[]
  variables_json: Array<Record<string, unknown>>
  tags_json: string[]
  verification_result_json: Record<string, unknown>
  quality_score?: number | null
  content_hash?: string | null
  create_user_id: number
  create_user_name?: string | null
  verified_by?: string | null
  verified_at?: string | null
  created_at: string
  updated_at: string
}

export interface VannaAskRunRecord {
  id: number
  kb_id: number
  datasource_id: number
  system_short: string
  env: string
  task_id?: number | null
  question_text: string
  rewritten_question?: string | null
  retrieval_snapshot_json: Record<string, unknown>
  prompt_snapshot_json: Record<string, unknown>
  generated_sql?: string | null
  sql_confidence?: number | null
  execution_mode?: string | null
  execution_status: VannaAskExecutionStatus | string
  execution_result_json: Record<string, unknown>
  approval_status?: string | null
  auto_train_entry_id?: number | null
  create_user_id: number
  create_user_name?: string | null
  created_at: string
  updated_at: string
}

export interface VannaSchemaHarvestPreviewTable {
  schema_name?: string | null
  table_name: string
  table_comment?: string | null
  column_count: number
  primary_keys: string[]
  foreign_key_count: number
}

export interface VannaSchemaHarvestPreviewResult {
  datasource_id: number
  system_short: string
  env: string
  db_type: string
  family: string
  selected_schema_names: string[]
  selected_table_names: string[]
  tables: VannaSchemaHarvestPreviewTable[]
}

export interface VannaSchemaHarvestCommitResult {
  job_id: number
  kb_id: number
  table_count: number
  column_count: number
  summary: Record<string, unknown>
}

export interface VannaAskResult {
  ask_run_id: number
  execution_status: string
  generated_sql?: string | null
  sql_confidence?: number | null
  execution_result?: Record<string, unknown> | null
  auto_train_entry_id?: number | null
}

export interface VannaSqlAssetRecord {
  id: number
  kb_id: number
  datasource_id: number
  asset_code: string
  name: string
  description?: string | null
  intent_summary?: string | null
  asset_kind: string
  status: VannaSqlAssetStatus | string
  system_short: string
  database_name?: string | null
  env: string
  match_keywords: string[]
  match_examples: string[]
  owner_user_id: number
  owner_user_name?: string | null
  current_version_id?: number | null
  origin_ask_run_id?: number | null
  origin_training_entry_id?: number | null
  created_at: string
  updated_at: string
}

export interface VannaSqlAssetVersionRecord {
  id: number
  asset_id: number
  version_no: number
  version_label?: string | null
  template_sql: string
  parameter_schema_json: Array<Record<string, unknown>>
  render_config_json: Record<string, unknown>
  statement_kind: string
  tables_read_json: string[]
  columns_read_json: string[]
  output_fields_json: string[]
  verification_result_json: Record<string, unknown>
  quality_status: string
  is_published: boolean
  published_at?: string | null
  created_by?: string | null
  created_at: string
}

