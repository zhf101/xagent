/// <reference types="@testing-library/jest-dom/vitest" />
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  materializeHttpAssetPayload,
  previewHttpAssetRequest,
  saveHttpAsset,
} from "./http-config-runtime"
import { createDefaultGdpHttpPayload } from "./gdp-types"
import { SchemaNode } from "./schema-tree-editor"

const apiRequestMock = vi.hoisted(() => vi.fn())

vi.mock("@/lib/utils", async () => {
  const actual = await vi.importActual<typeof import("@/lib/utils")>("@/lib/utils")
  return {
    ...actual,
    getApiUrl: () => "http://api.local",
  }
})

vi.mock("@/lib/api-wrapper", () => ({
  apiRequest: apiRequestMock,
}))

function createVisualTree(): SchemaNode[] {
  return [
    {
      id: "customer-id",
      name: "customerId",
      type: "string",
      description: "客户编号",
      required: true,
      route: { in: "path", name: "customer_id" },
    },
    {
      id: "trace-id",
      name: "traceId",
      type: "string",
      description: "链路追踪",
      required: false,
      route: { in: "header", name: "X-Trace-Id" },
    },
  ]
}

describe("http-config-runtime", () => {
  afterEach(() => {
    vi.clearAllMocks()
    apiRequestMock.mockReset()
  })

  it("uses backend normalize for visual payload materialization", async () => {
    const payload = createDefaultGdpHttpPayload()
    payload.execution_profile.direct_url = "https://api.example.com/customers/{customer_id}"
    payload.execution_profile.headers_json = [{ key: "X-App", value: "console" }]

    apiRequestMock.mockResolvedValueOnce({
      ok: true,
      json: vi.fn().mockResolvedValue({
        payload: {
          ...payload,
          tool_contract: {
            ...payload.tool_contract,
            input_schema_json: {
              type: "object",
              properties: {
                customerId: { type: "string", description: "客户编号" },
                traceId: { type: "string", description: "链路追踪" },
              },
              required: ["customerId"],
            },
          },
          execution_profile: {
            ...payload.execution_profile,
            headers_json: { "X-App": "console" },
            args_position_json: {
              customerId: { in: "path", name: "customer_id" },
              traceId: { in: "header", name: "X-Trace-Id" },
            },
          },
        },
      }),
    })

    const result = await materializeHttpAssetPayload({
      payload,
      inputEditMode: "visual",
      outputEditMode: "json",
      inputTree: createVisualTree(),
      outputTree: [],
      rawInputJson: "",
      rawOutputJson: JSON.stringify(payload.tool_contract.output_schema_json),
    })

    expect(apiRequestMock).toHaveBeenCalledTimes(1)
    expect(apiRequestMock).toHaveBeenCalledWith(
      "http://api.local/api/v1/gdp/http-assets/normalize",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          payload: {
            ...payload,
            tool_contract: {
              ...payload.tool_contract,
              output_schema_json: payload.tool_contract.output_schema_json,
            },
            execution_profile: {
              ...payload.execution_profile,
              headers_json: { "X-App": "console" },
            },
          },
          input_tree: createVisualTree(),
        }),
      })
    )
    expect(result.execution_profile.args_position_json).toEqual({
      customerId: { in: "path", name: "customer_id" },
      traceId: { in: "header", name: "X-Trace-Id" },
    })
  })

  it("normalizes first and then assembles preview request", async () => {
    const payload = createDefaultGdpHttpPayload()
    payload.execution_profile.direct_url = "https://api.example.com/customers/{customer_id}"

    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          payload: {
            ...payload,
            tool_contract: {
              ...payload.tool_contract,
              input_schema_json: {
                type: "object",
                properties: {
                  customerId: { type: "string" },
                  traceId: { type: "string" },
                },
                required: ["customerId"],
              },
            },
            execution_profile: {
              ...payload.execution_profile,
              headers_json: {},
              args_position_json: {
                customerId: { in: "path", name: "customer_id" },
                traceId: { in: "header", name: "X-Trace-Id" },
              },
            },
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          method: "POST",
          url: "https://api.example.com/customers/example_value",
          headers: { "X-Trace-Id": "example_value" },
          body: null,
        }),
      })

    const preview = await previewHttpAssetRequest({
      payload,
      inputEditMode: "visual",
      outputEditMode: "visual",
      inputTree: createVisualTree(),
      outputTree: [],
      rawInputJson: "",
      rawOutputJson: "",
    })

    expect(apiRequestMock).toHaveBeenCalledTimes(2)
    const assembleCall = apiRequestMock.mock.calls[1]
    expect(assembleCall[0]).toBe("http://api.local/api/v1/gdp/http-assets/assemble")
    expect(JSON.parse(String(assembleCall[1]?.body))).toEqual({
      payload: {
        ...payload,
        execution_profile: {
          ...payload.execution_profile,
          headers_json: {},
          args_position_json: {
            customerId: { in: "path", name: "customer_id" },
            traceId: { in: "header", name: "X-Trace-Id" },
          },
        },
        tool_contract: {
          ...payload.tool_contract,
          input_schema_json: {
            type: "object",
            properties: {
              customerId: { type: "string" },
              traceId: { type: "string" },
            },
            required: ["customerId"],
          },
        },
      },
      mock_args: {
        customerId: "example_value",
        traceId: "example_value",
      },
    })
    expect(preview.url).toContain("/customers/example_value")
  })

  it("saves json mode payload without extra normalize call", async () => {
    const payload = createDefaultGdpHttpPayload()
    payload.execution_profile.headers_json = [{ key: "X-App", value: "console" }]

    apiRequestMock.mockResolvedValueOnce({
      ok: true,
      json: vi.fn().mockResolvedValue({ data: {} }),
    })

    await saveHttpAsset({
      assetId: 11,
      payload,
      inputEditMode: "json",
      outputEditMode: "json",
      inputTree: [],
      outputTree: [],
      rawInputJson: JSON.stringify({
        type: "object",
        properties: { customerId: { type: "string" } },
        required: ["customerId"],
      }),
      rawOutputJson: JSON.stringify({
        type: "object",
        properties: { signupId: { type: "string" } },
      }),
    })

    expect(apiRequestMock).toHaveBeenCalledTimes(1)
    expect(apiRequestMock).toHaveBeenCalledWith(
      "http://api.local/api/v1/gdp/http-assets/11",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          ...payload,
          tool_contract: {
            ...payload.tool_contract,
            input_schema_json: {
              type: "object",
              properties: { customerId: { type: "string" } },
              required: ["customerId"],
            },
            output_schema_json: {
              type: "object",
              properties: { signupId: { type: "string" } },
            },
          },
          execution_profile: {
            ...payload.execution_profile,
            headers_json: { "X-App": "console" },
          },
        }),
      })
    )
  })
})
