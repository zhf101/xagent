"use client"

import { apiRequest } from "@/lib/api-wrapper"
import { getApiUrl } from "@/lib/utils"

import { GdpExecutionProfile, GdpHttpAssetPayload } from "./gdp-types"
import { SchemaNode } from "./schema-tree-editor"

export interface GdpHttpNormalizedPayload
  extends Omit<GdpHttpAssetPayload, "execution_profile"> {
  execution_profile: Omit<GdpExecutionProfile, "headers_json"> & {
    headers_json: Record<string, string>
  }
}

export interface HttpDraftMaterializeOptions {
  payload: GdpHttpAssetPayload
  inputEditMode: "visual" | "json"
  outputEditMode: "visual" | "json"
  inputTree: SchemaNode[]
  outputTree: SchemaNode[]
  rawInputJson: string
  rawOutputJson: string
}

export interface HttpRequestPreviewResponse {
  url: string
  method: string
  headers: Record<string, string>
  body?: string | null
}

function headersToRecord(
  headers: GdpExecutionProfile["headers_json"] | Record<string, unknown> | undefined
): Record<string, string> {
  if (!headers) {
    return {}
  }
  if (Array.isArray(headers)) {
    return headers.reduce<Record<string, string>>((acc, item) => {
      if (item?.key && item?.value) {
        acc[String(item.key)] = String(item.value)
      }
      return acc
    }, {})
  }

  return Object.entries(headers).reduce<Record<string, string>>((acc, [key, value]) => {
    if (value !== undefined && value !== null && String(key).trim()) {
      acc[String(key)] = String(value)
    }
    return acc
  }, {})
}

function headersToList(
  headers: GdpExecutionProfile["headers_json"] | Record<string, unknown> | undefined
): { key: string; value: string }[] {
  if (!headers) {
    return []
  }
  if (Array.isArray(headers)) {
    return headers
      .filter(item => item?.key && item?.value)
      .map(item => ({ key: String(item.key), value: String(item.value) }))
  }
  return Object.entries(headers).map(([key, value]) => ({
    key: String(key),
    value: String(value),
  }))
}

function parseSchemaJson(text: string, label: string): Record<string, unknown> {
  try {
    return JSON.parse(text || "{}")
  } catch {
    throw new Error(`${label} JSON 格式错误`)
  }
}

async function readErrorDetail(
  response: Response,
  fallbackMessage: string
): Promise<string> {
  try {
    const data = await response.json()
    if (typeof data?.detail === "string" && data.detail.trim()) {
      return data.detail
    }
  } catch {}
  return fallbackMessage
}

function buildBackendPayload(payload: GdpHttpAssetPayload): GdpHttpNormalizedPayload {
  return {
    ...payload,
    execution_profile: {
      ...payload.execution_profile,
      headers_json: headersToRecord(payload.execution_profile.headers_json),
    },
  }
}

export function coerceHttpAssetPayloadFromApi(data: GdpHttpAssetPayload): GdpHttpAssetPayload {
  return {
    ...data,
    execution_profile: {
      ...data.execution_profile,
      auth_json: data.execution_profile.auth_json?.type
        ? data.execution_profile.auth_json
        : { type: "none", ...(data.execution_profile.auth_json || {}) },
      headers_json: headersToList(data.execution_profile.headers_json),
    },
  }
}

export async function normalizeVisualHttpAssetDraft(options: {
  payload: GdpHttpAssetPayload
  inputTree?: SchemaNode[]
  outputTree?: SchemaNode[]
}): Promise<GdpHttpNormalizedPayload> {
  const requestBody: Record<string, unknown> = {
    payload: buildBackendPayload(options.payload),
  }
  if (options.inputTree) {
    requestBody.input_tree = options.inputTree
  }
  if (options.outputTree) {
    requestBody.output_tree = options.outputTree
  }

  const response = await apiRequest(`${getApiUrl()}/api/v1/gdp/http-assets/normalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(requestBody),
  })

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "配置归一化失败"))
  }

  const data = await response.json()
  return data.payload as GdpHttpNormalizedPayload
}

export async function materializeHttpAssetPayload(
  options: HttpDraftMaterializeOptions
): Promise<GdpHttpNormalizedPayload> {
  let nextPayload: GdpHttpAssetPayload = {
    ...options.payload,
    tool_contract: {
      ...options.payload.tool_contract,
    },
    execution_profile: {
      ...options.payload.execution_profile,
    },
  }

  if (options.inputEditMode === "json") {
    nextPayload = {
      ...nextPayload,
      tool_contract: {
        ...nextPayload.tool_contract,
        input_schema_json: parseSchemaJson(options.rawInputJson, "输入参数"),
      },
    }
  }

  if (options.outputEditMode === "json") {
    nextPayload = {
      ...nextPayload,
      tool_contract: {
        ...nextPayload.tool_contract,
        output_schema_json: parseSchemaJson(options.rawOutputJson, "输出参数"),
      },
    }
  }

  if (
    options.inputEditMode === "visual" ||
    options.outputEditMode === "visual"
  ) {
    return normalizeVisualHttpAssetDraft({
      payload: nextPayload,
      inputTree: options.inputEditMode === "visual" ? options.inputTree : undefined,
      outputTree:
        options.outputEditMode === "visual" ? options.outputTree : undefined,
    })
  }

  return buildBackendPayload(nextPayload)
}

export async function previewHttpAssetRequest(
  options: HttpDraftMaterializeOptions
): Promise<HttpRequestPreviewResponse> {
  const payload = await materializeHttpAssetPayload(options)
  const mockArgs =
    options.inputEditMode === "visual"
      ? generateMockArgsFromTree(options.inputTree)
      : generateMockArgsFromSchema(payload.tool_contract.input_schema_json)

  const response = await apiRequest(`${getApiUrl()}/api/v1/gdp/http-assets/assemble`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      payload,
      mock_args: mockArgs,
    }),
  })

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "请求拼装失败"))
  }

  return response.json()
}

export async function saveHttpAsset(
  options: HttpDraftMaterializeOptions & { assetId?: number }
): Promise<Response> {
  const payload = await materializeHttpAssetPayload(options)
  return apiRequest(`${getApiUrl()}/api/v1/gdp/http-assets${options.assetId ? `/${options.assetId}` : ""}`, {
    method: options.assetId ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
}

function generateMockArgsFromTree(nodes: SchemaNode[]): Record<string, unknown> {
  const args: Record<string, unknown> = {}
  nodes.forEach(node => {
    if (!node.name) {
      return
    }

    if (node.type === "string") {
      args[node.name] = node.defaultValue || "example_value"
      return
    }
    if (node.type === "number" || node.type === "integer") {
      args[node.name] = Number(node.defaultValue) || 123
      return
    }
    if (node.type === "boolean") {
      args[node.name] = node.defaultValue === "true"
      return
    }
    if (node.type === "object") {
      args[node.name] = generateMockArgsFromTree(node.children || [])
      return
    }
    if (node.type === "array") {
      args[node.name] = [generateMockArgsFromTree(node.children || [])]
    }
  })
  return args
}

function generateMockArgsFromSchema(
  inputSchema: Record<string, unknown>
): Record<string, unknown> {
  const args: Record<string, unknown> = {}
  const properties = (inputSchema?.properties || {}) as Record<
    string,
    { type?: string }
  >

  Object.keys(properties).forEach(key => {
    const schema = properties[key]
    if (schema?.type === "string") {
      args[key] = "test"
    } else if (schema?.type === "number" || schema?.type === "integer") {
      args[key] = 1
    }
  })

  return args
}
