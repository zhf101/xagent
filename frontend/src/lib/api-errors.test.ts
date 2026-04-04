/// <reference types="@testing-library/jest-dom/vitest" />
import { describe, expect, it } from "vitest"

import {
  formatApiErrorMessage,
  getApiErrorMessage,
  getApprovalSubmissionMessage,
} from "./api-errors"

describe("api-errors", () => {
  it("formats fastapi validation error arrays into readable text", () => {
    expect(
      formatApiErrorMessage([
        {
          type: "missing",
          loc: ["body", "system_short"],
          msg: "Field required",
        },
        {
          type: "missing",
          loc: ["body", "env"],
          msg: "Field required",
        },
      ])
    ).toBe("body.system_short: Field required；body.env: Field required")
  })

  it("extracts detail messages from api payloads", () => {
    expect(
      getApiErrorMessage(
        {
          detail: [
            { loc: ["body", "system_short"], msg: "Field required" },
          ],
        },
        "fallback"
      )
    ).toBe("body.system_short: Field required")
  })

  it("prefers backend approval submission messages when present", () => {
    expect(
      getApprovalSubmissionMessage(
        {
          message: "submitted for approval",
          data: { status: "pending_approval" },
        },
        "创建申请已提交，等待系统管理员审批"
      )
    ).toBe("submitted for approval")
  })
})
