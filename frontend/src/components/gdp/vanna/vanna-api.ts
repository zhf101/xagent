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
  VannaTrainingEntryRecord,
} from "./vanna-types"

type JsonEnvelope<T> = {
  data: T
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
  return requestEnvelope<VannaKnowledgeBaseRecord[]>("/api/vanna/kbs")
}

export async function getVannaKnowledgeBase(kbId: number) {
  return requestEnvelope<VannaKnowledgeBaseRecord>(`/api/vanna/kbs/${kbId}`)
}

export async function createVannaKnowledgeBase(payload: {
  datasource_id: number
  name?: string
  description?: string
}) {
  return requestEnvelope<VannaKnowledgeBaseRecord>("/api/vanna/kbs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function listText2SqlDatabases() {
  return requestJson<Text2SqlDatabaseRecord[]>(
    buildUrl("/api/text2sql/databases")
  )
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
  return requestEnvelope<VannaSchemaTableRecord[]>(
    buildUrl("/api/vanna/schema-tables", filters)
  )
}

export async function listSchemaColumns(filters: {
  kb_id?: number
  datasource_id?: number
  schema_name?: string
  table_name?: string
  column_name?: string
}) {
  return requestEnvelope<VannaSchemaColumnRecord[]>(
    buildUrl("/api/vanna/schema-columns", filters)
  )
}

export async function listHarvestJobs(filters: {
  kb_id?: number
  datasource_id?: number
  status?: string
}) {
  return requestEnvelope<VannaSchemaHarvestJobRecord[]>(
    buildUrl("/api/vanna/harvest-jobs", filters)
  )
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
  return requestEnvelope<VannaTrainingEntryRecord | VannaTrainingEntryRecord[]>(
    "/api/vanna/train",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }
  )
}

export async function listTrainingEntries(filters: {
  kb_id?: number
  datasource_id?: number
  entry_type?: string
  lifecycle_status?: string
}) {
  return requestEnvelope<VannaTrainingEntryRecord[]>(
    buildUrl("/api/vanna/entries", filters)
  )
}

export async function publishTrainingEntry(entryId: number) {
  return requestEnvelope<VannaTrainingEntryRecord>(
    `/api/vanna/entries/${entryId}/publish`,
    {
      method: "POST",
    }
  )
}

export async function archiveTrainingEntry(entryId: number) {
  return requestEnvelope<VannaTrainingEntryRecord>(
    `/api/vanna/entries/${entryId}/archive`,
    {
      method: "POST",
    }
  )
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
  return requestEnvelope<VannaAskRunRecord[]>(
    buildUrl("/api/vanna/ask-runs", filters)
  )
}
