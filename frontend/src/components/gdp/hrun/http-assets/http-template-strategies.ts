import { GdpHttpAssetPayload } from "./gdp-types"

export type RequestBodyStrategy = "none" | "json" | "custom"
export type SuccessResponseStrategy = "default" | "custom" | "append"

export interface HttpTemplateStrategyState {
  requestBodyStrategy: RequestBodyStrategy
  requestBodyTemplate: string
  successResponseStrategy: SuccessResponseStrategy
  successResponseTemplate: string
  successResponsePrepend: string
  successResponseAppend: string
}

/**
 * 把后端保存的 request/response template 反解成页面编辑态。
 *
 * 这里单独抽成纯函数，核心目的不是“代码好看”，而是把协议语义固定住：
 * 以后即使有人重做页面，只要还复用这层逻辑，就不会再把
 * `argsToJsonBody / argsToUrlParam / body / prependBody / appendBody`
 * 这些兼容语义悄悄丢掉。
 */
export function deriveHttpTemplateStrategyState(
  payload: GdpHttpAssetPayload
): HttpTemplateStrategyState {
  const requestTemplate = payload.execution_profile.request_template_json || {}
  const responseTemplate = payload.execution_profile.response_template_json || {}
  const method = payload.execution_profile.method

  let requestBodyStrategy: RequestBodyStrategy
  if (typeof requestTemplate.body === "string") {
    requestBodyStrategy = "custom"
  } else if (requestTemplate.argsToUrlParam) {
    requestBodyStrategy = "none"
  } else if (requestTemplate.argsToJsonBody) {
    requestBodyStrategy = "json"
  } else {
    requestBodyStrategy = method === "GET" ? "none" : "json"
  }

  let successResponseStrategy: SuccessResponseStrategy = "default"
  if (typeof responseTemplate.body === "string") {
    successResponseStrategy = "custom"
  } else if (
    typeof responseTemplate.prependBody === "string" ||
    typeof responseTemplate.appendBody === "string"
  ) {
    successResponseStrategy = "append"
  }

  return {
    requestBodyStrategy,
    requestBodyTemplate:
      typeof requestTemplate.body === "string" ? requestTemplate.body : "",
    successResponseStrategy,
    successResponseTemplate:
      typeof responseTemplate.body === "string" ? responseTemplate.body : "",
    successResponsePrepend:
      typeof responseTemplate.prependBody === "string"
        ? responseTemplate.prependBody
        : "",
    successResponseAppend:
      typeof responseTemplate.appendBody === "string"
        ? responseTemplate.appendBody
        : "",
  }
}

/**
 * 根据页面上选择的策略，回写真正要送给后端的 payload。
 *
 * 关键约束：
 * 1. 请求体三种策略必须互斥，避免同时残留旧字段导致校验失败。
 * 2. GET 永远不能带 body，所以即使 UI 传错了策略，也要在这里兜底收敛。
 * 3. 成功响应的 `body` 与 `prependBody/appendBody` 也必须互斥。
 */
export function applyHttpTemplateStrategyState(
  payload: GdpHttpAssetPayload,
  state: HttpTemplateStrategyState
): GdpHttpAssetPayload {
  const requestTemplate = {
    ...(payload.execution_profile.request_template_json || {}),
  } as Record<string, unknown>
  delete requestTemplate.body
  delete requestTemplate.argsToJsonBody
  delete requestTemplate.argsToUrlParam

  if (payload.execution_profile.method === "GET") {
    requestTemplate.argsToUrlParam = true
  } else if (state.requestBodyStrategy === "custom") {
    requestTemplate.body = state.requestBodyTemplate
  } else if (state.requestBodyStrategy === "none") {
    requestTemplate.argsToUrlParam = true
  } else {
    requestTemplate.argsToJsonBody = true
  }

  const responseTemplate = {
    ...(payload.execution_profile.response_template_json || {}),
  } as Record<string, unknown>
  delete responseTemplate.body
  delete responseTemplate.prependBody
  delete responseTemplate.appendBody

  if (state.successResponseStrategy === "custom") {
    responseTemplate.body = state.successResponseTemplate
  } else if (state.successResponseStrategy === "append") {
    responseTemplate.prependBody = state.successResponsePrepend
    responseTemplate.appendBody = state.successResponseAppend
  }

  return {
    ...payload,
    execution_profile: {
      ...payload.execution_profile,
      request_template_json: requestTemplate,
      response_template_json: responseTemplate,
    },
  }
}
