export interface GdpHttpResource {
  id?: number
  resource_key: string
  system_short: string
  visibility: "private" | "shared" | "global"
  summary: string
  tags_json: string[]
  status?: number // 0=draft, 1=active, 2=deleted
}

export interface GdpToolAnnotations {
  title?: string
  readOnlyHint?: boolean
  destructiveHint?: boolean
  idempotentHint?: boolean
  openWorldHint?: boolean
}

export interface GdpToolContract {
  tool_name: string
  tool_description: string
  input_schema_json: any
  output_schema_json: any
  annotations_json: GdpToolAnnotations
}

export interface GdpExecutionProfile {
  method: "GET" | "POST"
  url_mode: "direct" | "tag"
  direct_url?: string
  sys_label?: string
  url_suffix?: string
  args_position_json: Record<string, any>
  request_template_json: {
    url?: string
    method?: string
    headers?: { key: string; value: string }[]
    body?: string
    argsToJsonBody?: boolean
    argsToUrlParam?: boolean
  }
  response_template_json: {
    body?: string
    prependBody?: string
    appendBody?: string
  }
  error_response_template?: string
  auth_json: {
    type: "none" | "bearer" | "api_key" | "basic"
    token?: string
    header_name?: string
    username?: string
    password?: string
  }
  headers_json: { key: string; value: string }[]
  timeout_seconds: number
}

export interface GdpHttpAssetPayload {
  resource: GdpHttpResource
  tool_contract: GdpToolContract
  execution_profile: GdpExecutionProfile
}

export const createDefaultGdpHttpPayload = (): GdpHttpAssetPayload => ({
  resource: {
    resource_key: "",
    system_short: "",
    visibility: "private",
    summary: "",
    tags_json: [],
  },
  tool_contract: {
    tool_name: "",
    tool_description: "",
    input_schema_json: { type: "object", properties: {}, required: [] },
    output_schema_json: { type: "object", properties: {} },
    annotations_json: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false,
    },
  },
  execution_profile: {
    method: "POST",
    url_mode: "direct",
    direct_url: "",
    args_position_json: {},
    request_template_json: {},
    response_template_json: {},
    auth_json: { type: "none" },
    headers_json: [],
    timeout_seconds: 30,
  },
})
