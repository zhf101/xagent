"use client"

import { apiRequest } from "@/lib/api-wrapper"
import { getApiUrl } from "@/lib/utils"
import type {
  Text2SqlDatabaseRecord,
  VannaAskResult,
  VannaAskRunRecord,
  VannaKnowledgeBaseRecord,
  VannaSchemaColumnRecord,
  VannaSchemaHarvestCommitResult,
  VannaSchemaHarvestJobRecord,
  VannaSchemaHarvestPreviewResult,
  VannaSchemaTableRecord,
  VannaSqlAssetRecord,
  VannaSqlAssetVersionRecord,
  VannaTrainingEntryRecord,
} from "./vanna-types"

type JsonEnvelope<T> = {
  data: T
}

function normalizeStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter((item): item is string => typeof item === "string")
}

function normalizeRecordArray(
  value: unknown
): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter(
    (item): item is Record<string, unknown> =>
      typeof item === "object" && item !== null && !Array.isArray(item)
  )
}

function normalizeObjectRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {}
  }
  return value as Record<string, unknown>
}

function normalizeKnowledgeBaseRecord(
  knowledgeBase: VannaKnowledgeBaseRecord
): VannaKnowledgeBaseRecord {
  return {
    ...knowledgeBase,
    description: knowledgeBase.description ?? null,
    owner_user_name: knowledgeBase.owner_user_name ?? null,
    datasource_name: knowledgeBase.datasource_name ?? null,
    database_name: knowledgeBase.database_name ?? null,
    db_type: knowledgeBase.db_type ?? null,
    dialect: knowledgeBase.dialect ?? null,
    embedding_model: knowledgeBase.embedding_model ?? null,
    llm_model: knowledgeBase.llm_model ?? null,
    last_train_at: knowledgeBase.last_train_at ?? null,
    last_ask_at: knowledgeBase.last_ask_at ?? null,
  }
}

function normalizeSchemaTableRecord(
  table: VannaSchemaTableRecord
): VannaSchemaTableRecord {
  return {
    ...table,
    primary_key_json: normalizeStringArray(table.primary_key_json),
    foreign_keys_json: normalizeRecordArray(table.foreign_keys_json),
    indexes_json: normalizeRecordArray(table.indexes_json),
    constraints_json: normalizeRecordArray(table.constraints_json),
  }
}

function normalizeSchemaColumnRecord(
  column: VannaSchemaColumnRecord
): VannaSchemaColumnRecord {
  return {
    ...column,
    allowed_values_json: normalizeStringArray(column.allowed_values_json),
    sample_values_json: normalizeStringArray(column.sample_values_json),
    semantic_tags_json: normalizeStringArray(column.semantic_tags_json),
    allowed_values_override_json: normalizeStringArray(
      column.allowed_values_override_json
    ),
    sample_values_override_json: normalizeStringArray(
      column.sample_values_override_json
    ),
    effective_allowed_values_json: normalizeStringArray(
      column.effective_allowed_values_json
    ),
    effective_sample_values_json: normalizeStringArray(
      column.effective_sample_values_json
    ),
    annotation: column.annotation
      ? {
          ...column.annotation,
          allowed_values_override_json: normalizeStringArray(
            column.annotation.allowed_values_override_json
          ),
          sample_values_override_json: normalizeStringArray(
            column.annotation.sample_values_override_json
          ),
        }
      : null,
  }
}

function normalizeHarvestJobRecord(
  job: VannaSchemaHarvestJobRecord
): VannaSchemaHarvestJobRecord {
  return {
    ...job,
    schema_names_json: normalizeStringArray(job.schema_names_json),
    table_names_json: normalizeStringArray(job.table_names_json),
    request_payload_json: normalizeObjectRecord(job.request_payload_json),
    result_payload_json: normalizeObjectRecord(job.result_payload_json),
  }
}

function normalizeTrainingEntryRecord(
  entry: VannaTrainingEntryRecord
): VannaTrainingEntryRecord {
  return {
    ...entry,
    tables_read_json: normalizeStringArray(entry.tables_read_json),
    columns_read_json: normalizeStringArray(entry.columns_read_json),
    output_fields_json: normalizeStringArray(entry.output_fields_json),
    variables_json: normalizeRecordArray(entry.variables_json),
    tags_json: normalizeStringArray(entry.tags_json),
    verification_result_json: normalizeObjectRecord(entry.verification_result_json),
  }
}

function normalizeAskRunRecord(run: VannaAskRunRecord): VannaAskRunRecord {
  return {
    ...run,
    retrieval_snapshot_json: normalizeObjectRecord(run.retrieval_snapshot_json),
    prompt_snapshot_json: normalizeObjectRecord(run.prompt_snapshot_json),
    execution_result_json: normalizeObjectRecord(run.execution_result_json),
  }
}

function normalizeSqlAssetRecord(asset: VannaSqlAssetRecord): VannaSqlAssetRecord {
  return {
    ...asset,
    database_name: asset.database_name ?? null,
    match_keywords: normalizeStringArray(asset.match_keywords),
    match_examples: normalizeStringArray(asset.match_examples),
  }
}

function normalizeText2SqlDatabaseRecord(
  database: Text2SqlDatabaseRecord
): Text2SqlDatabaseRecord {
  return {
    ...database,
    database_name: database.database_name ?? null,
    table_count: database.table_count ?? null,
    last_connected_at: database.last_connected_at ?? null,
    error_message: database.error_message ?? null,
  }
}

function normalizeSqlAssetVersionRecord(
  version: VannaSqlAssetVersionRecord
): VannaSqlAssetVersionRecord {
  return {
    ...version,
    parameter_schema_json: normalizeRecordArray(version.parameter_schema_json),
    render_config_json: normalizeObjectRecord(version.render_config_json),
    tables_read_json: normalizeStringArray(version.tables_read_json),
    columns_read_json: normalizeStringArray(version.columns_read_json),
    output_fields_json: normalizeStringArray(version.output_fields_json),
    verification_result_json: normalizeObjectRecord(version.verification_result_json),
  }
}

function buildUrl(path: string, query?: Record<string, string | number | undefined | null>) {
  const baseUrl = `${getApiUrl()}${path}`
  if (!query) {
    return baseUrl
  }

  const search = new URLSearchParams()
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return
    }
    search.set(key, String(value))
  })
  const queryString = search.toString()
  return queryString ? `${baseUrl}?${queryString}` : baseUrl
}

// 统一读取 FastAPI 错误体，避免每个页面重复写错误解析。
async function parseError(response: Response) {
  try {
    const payload = await response.json()
    if (typeof payload?.detail === "string") {
      return payload.detail
    }
  } catch {
    // 忽略 JSON 解析失败，回退通用文案。
  }
  return `请求失败 (${response.status})`
}

async function requestJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await apiRequest(url, options)
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
  return response.json() as Promise<T>
}

async function requestEnvelope<T>(
  pathOrUrl: string,
  options?: RequestInit
): Promise<T> {
  const url = pathOrUrl.startsWith("/api/")
    ? buildUrl(pathOrUrl)
    : pathOrUrl
  const payload = await requestJson<JsonEnvelope<T>>(url, options)
  return payload.data
}

export async function listVannaKnowledgeBases() {
  const rows = await requestEnvelope<VannaKnowledgeBaseRecord[]>("/api/vanna/kbs")
  return rows.map(normalizeKnowledgeBaseRecord)
}

export async function getVannaKnowledgeBase(kbId: number) {
  const row = await requestEnvelope<VannaKnowledgeBaseRecord>(`/api/vanna/kbs/${kbId}`)
  return normalizeKnowledgeBaseRecord(row)
}

export async function createVannaKnowledgeBase(payload: {
  datasource_id: number
  name?: string
  description?: string
  default_top_k_sql?: number
  default_top_k_schema?: number
  default_top_k_doc?: number
  embedding_model?: string
  llm_model?: string
}) {
  const row = await requestEnvelope<VannaKnowledgeBaseRecord>("/api/vanna/kbs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
  return normalizeKnowledgeBaseRecord(row)
}

export async function listText2SqlDatabases() {
  const rows = await requestJson<Text2SqlDatabaseRecord[]>(
    buildUrl("/api/text2sql/databases")
  )
  return rows.map(normalizeText2SqlDatabaseRecord)
}

export async function previewSchemaHarvest(payload: {
  datasource_id: number
  schema_names?: string[]
  table_names?: string[]
}) {
  return requestEnvelope<VannaSchemaHarvestPreviewResult>(
    "/api/vanna/schema-harvest/preview",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }
  )
}

export async function commitSchemaHarvest(payload: {
  datasource_id: number
  schema_names?: string[]
  table_names?: string[]
}) {
  return requestEnvelope<VannaSchemaHarvestCommitResult>(
    "/api/vanna/schema-harvest/commit",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }
  )
}

export async function listSchemaTables(filters: {
  kb_id?: number
  datasource_id?: number
  status?: string
  schema_name?: string
  table_name?: string
}) {
  const rows = await requestEnvelope<VannaSchemaTableRecord[]>(
    buildUrl("/api/vanna/schema-tables", filters)
  )
  return rows.map(normalizeSchemaTableRecord)
}

export async function listSchemaColumns(filters: {
  kb_id?: number
  datasource_id?: number
  schema_name?: string
  table_name?: string
  column_name?: string
}) {
  const rows = await requestEnvelope<VannaSchemaColumnRecord[]>(
    buildUrl("/api/vanna/schema-columns", filters)
  )
  return rows.map(normalizeSchemaColumnRecord)
}

export async function updateSchemaColumnAnnotation(
  columnId: number,
  payload: {
    business_description?: string | null
    comment_override?: string | null
    default_value_override?: string | null
    allowed_values_override_json?: string[] | null
    sample_values_override_json?: string[] | null
    update_source?: string
  }
) {
  const row = await requestEnvelope<VannaSchemaColumnRecord>(
    `/api/vanna/schema-columns/${columnId}/annotation`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }
  )
  return normalizeSchemaColumnRecord(row)
}

export async function listHarvestJobs(filters: {
  kb_id?: number
  datasource_id?: number
  status?: string
}) {
  const rows = await requestEnvelope<VannaSchemaHarvestJobRecord[]>(
    buildUrl("/api/vanna/harvest-jobs", filters)
  )
  return rows.map(normalizeHarvestJobRecord)
}

export async function trainVannaEntry(payload: {
  datasource_id: number
  question?: string
  sql?: string
  documentation?: string
  title?: string
  bootstrap_schema?: boolean
  publish?: boolean
}) {
  const data = await requestEnvelope<VannaTrainingEntryRecord | VannaTrainingEntryRecord[]>(
    "/api/vanna/train",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }
  )
  return Array.isArray(data)
    ? data.map(normalizeTrainingEntryRecord)
    : normalizeTrainingEntryRecord(data)
}

export async function listTrainingEntries(filters: {
  kb_id?: number
  datasource_id?: number
  entry_type?: string
  lifecycle_status?: string
}) {
  const rows = await requestEnvelope<VannaTrainingEntryRecord[]>(
    buildUrl("/api/vanna/entries", filters)
  )
  return rows.map(normalizeTrainingEntryRecord)
}

export async function getTrainingEntry(entryId: number) {
  const row = await requestEnvelope<VannaTrainingEntryRecord>(
    `/api/vanna/entries/${entryId}`
  )
  return normalizeTrainingEntryRecord(row)
}

export async function publishTrainingEntry(entryId: number) {
  const row = await requestEnvelope<VannaTrainingEntryRecord>(
    `/api/vanna/entries/${entryId}/publish`,
    {
      method: "POST",
    }
  )
  return normalizeTrainingEntryRecord(row)
}

export async function updateTrainingEntry(
  entryId: number,
  payload: {
    question?: string
    sql?: string
    sql_explanation?: string
    title?: string
    documentation?: string
  }
) {
  const row = await requestEnvelope<VannaTrainingEntryRecord>(
    `/api/vanna/entries/${entryId}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }
  )
  return normalizeTrainingEntryRecord(row)
}

export async function archiveTrainingEntry(entryId: number) {
  const row = await requestEnvelope<VannaTrainingEntryRecord>(
    `/api/vanna/entries/${entryId}/archive`,
    {
      method: "POST",
    }
  )
  return normalizeTrainingEntryRecord(row)
}

export async function deleteTrainingEntry(entryId: number) {
  return requestEnvelope<{ id: number; deleted: boolean }>(
    `/api/vanna/entries/${entryId}`,
    {
      method: "DELETE",
    }
  )
}

export async function promoteAskRunToSqlAsset(
  askRunId: number,
  payload: {
    asset_code: string
    name: string
    description?: string
    intent_summary?: string
    asset_kind?: string
    match_keywords?: string[]
    match_examples?: string[]
    parameter_schema_json?: Array<Record<string, unknown>>
    render_config_json?: Record<string, unknown>
    version_label?: string
  }
) {
  return requestEnvelope<{
    asset: Record<string, unknown>
    version: Record<string, unknown>
  }>(`/api/vanna/ask-runs/${askRunId}/promote`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function promoteTrainingEntryToSqlAsset(
  entryId: number,
  payload: {
    asset_code: string
    name: string
    description?: string
    intent_summary?: string
    asset_kind?: string
    match_keywords?: string[]
    match_examples?: string[]
    parameter_schema_json?: Array<Record<string, unknown>>
    render_config_json?: Record<string, unknown>
    version_label?: string
  }
) {
  return requestEnvelope<{
    asset: Record<string, unknown>
    version: Record<string, unknown>
  }>(`/api/vanna/entries/${entryId}/promote`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function askVannaSql(payload: {
  datasource_id: number
  kb_id?: number
  task_id?: number
  question: string
  auto_run?: boolean
  auto_train_on_success?: boolean
  top_k_sql?: number
  top_k_schema?: number
  top_k_doc?: number
}) {
  return requestEnvelope<VannaAskResult>("/api/vanna/ask", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function listAskRuns(filters: {
  kb_id?: number
  datasource_id?: number
  execution_status?: string
}) {
  const rows = await requestEnvelope<VannaAskRunRecord[]>(
    buildUrl("/api/vanna/ask-runs", filters)
  )
  return rows.map(normalizeAskRunRecord)
}

export async function listVannaSqlAssets(filters: {
  kb_id?: number
  datasource_id?: number
  system_short?: string
  database_name?: string
  env?: string
  status?: string
  keyword?: string
}) {
  const rows = await requestEnvelope<VannaSqlAssetRecord[]>(
    buildUrl("/api/vanna/assets", filters)
  )
  return rows.map(normalizeSqlAssetRecord)
}

export async function getVannaSqlAsset(assetId: number) {
  const row = await requestEnvelope<VannaSqlAssetRecord>(`/api/vanna/assets/${assetId}`)
  return normalizeSqlAssetRecord(row)
}

export async function listVannaSqlAssetVersions(assetId: number) {
  const rows = await requestEnvelope<VannaSqlAssetVersionRecord[]>(
    `/api/vanna/assets/${assetId}/versions`
  )
  return rows.map(normalizeSqlAssetVersionRecord)
}

export async function publishVannaSqlAsset(
  assetId: number,
  payload: {
    version_id: number
  }
) {
  const row = await requestEnvelope<VannaSqlAssetVersionRecord>(
    `/api/vanna/assets/${assetId}/publish`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }
  )
  return normalizeSqlAssetVersionRecord(row)
}

export async function updateVannaSqlAsset(
  assetId: number,
  payload: {
    asset_code: string
    name: string
    description?: string
    intent_summary?: string
    asset_kind?: string
    match_keywords?: string[]
    match_examples?: string[]
    template_sql: string
    version_label?: string
  }
) {
  return requestEnvelope<{
    asset: VannaSqlAssetRecord
    version: VannaSqlAssetVersionRecord
  }>(`/api/vanna/assets/${assetId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function archiveVannaSqlAsset(assetId: number) {
  const row = await requestEnvelope<VannaSqlAssetRecord>(
    `/api/vanna/assets/${assetId}`,
    {
      method: "DELETE",
    }
  )
  return normalizeSqlAssetRecord(row)
}
