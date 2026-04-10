import { describe, expect, it } from "vitest"

import { createDefaultGdpHttpPayload } from "./gdp-types"
import {
  applyHttpTemplateStrategyState,
  deriveHttpTemplateStrategyState,
} from "./http-template-strategies"

describe("http-template-strategies", () => {
  it("defaults POST assets to json body and default response passthrough", () => {
    const payload = createDefaultGdpHttpPayload()

    expect(deriveHttpTemplateStrategyState(payload)).toEqual({
      requestBodyStrategy: "json",
      requestBodyTemplate: "",
      successResponseStrategy: "default",
      successResponseTemplate: "",
      successResponsePrepend: "",
      successResponseAppend: "",
    })
  })

  it("restores custom request body and append response strategy from payload", () => {
    const payload = createDefaultGdpHttpPayload()
    payload.execution_profile.request_template_json = {
      headers: [{ key: "X-App", value: "console" }],
      body: '{"func":"updatedishui.lgx","data":{{ args | tojson }}}',
    }
    payload.execution_profile.response_template_json = {
      prependBody: "这是结果摘要：",
      appendBody: "请继续解释关键字段。",
    }

    expect(deriveHttpTemplateStrategyState(payload)).toEqual({
      requestBodyStrategy: "custom",
      requestBodyTemplate:
        '{"func":"updatedishui.lgx","data":{{ args | tojson }}}',
      successResponseStrategy: "append",
      successResponseTemplate: "",
      successResponsePrepend: "这是结果摘要：",
      successResponseAppend: "请继续解释关键字段。",
    })
  })

  it("applies custom request body without keeping conflicting auto-body flags", () => {
    const payload = createDefaultGdpHttpPayload()
    payload.execution_profile.request_template_json = {
      url: "https://api.example.com/orders",
      headers: [{ key: "X-App", value: "console" }],
      argsToJsonBody: true,
      argsToUrlParam: true,
    }
    payload.execution_profile.response_template_json = {
      body: "old body",
      prependBody: "old prepend",
    }

    const nextPayload = applyHttpTemplateStrategyState(payload, {
      requestBodyStrategy: "custom",
      requestBodyTemplate:
        '{"func":"updatedishui.lgx","data":{{ args | tojson }}}',
      successResponseStrategy: "append",
      successResponseTemplate: "ignored",
      successResponsePrepend: "前缀",
      successResponseAppend: "后缀",
    })

    expect(nextPayload.execution_profile.request_template_json).toEqual({
      url: "https://api.example.com/orders",
      headers: [{ key: "X-App", value: "console" }],
      body: '{"func":"updatedishui.lgx","data":{{ args | tojson }}}',
    })
    expect(nextPayload.execution_profile.response_template_json).toEqual({
      prependBody: "前缀",
      appendBody: "后缀",
    })
  })

  it("forces GET assets back to url params even if UI state still points at body mode", () => {
    const payload = createDefaultGdpHttpPayload()
    payload.execution_profile.method = "GET"
    payload.execution_profile.request_template_json = {
      url: "https://api.example.com/orders",
    }

    const nextPayload = applyHttpTemplateStrategyState(payload, {
      requestBodyStrategy: "custom",
      requestBodyTemplate: '{"ignored":true}',
      successResponseStrategy: "default",
      successResponseTemplate: "",
      successResponsePrepend: "",
      successResponseAppend: "",
    })

    expect(nextPayload.execution_profile.request_template_json).toEqual({
      url: "https://api.example.com/orders",
      argsToUrlParam: true,
    })
  })
})
