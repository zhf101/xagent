/// <reference types="@testing-library/jest-dom/vitest" />
import React from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, render, screen, waitFor } from "@testing-library/react"

const apiRequestMock = vi.hoisted(() => vi.fn())

vi.mock("@/lib/utils", () => ({
  getApiUrl: () => "http://api.local",
}))

vi.mock("@/lib/api-wrapper", () => ({
  apiRequest: apiRequestMock,
}))

import { ContextDrawer } from "./context-drawer"

function buildResponse(data: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(data),
  }
}

describe("ContextDrawer", () => {
  beforeEach(() => {
    apiRequestMock.mockReset()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it("在任务仍为 running 时持续轮询上下文接口", async () => {
    vi.useFakeTimers()
    apiRequestMock.mockResolvedValue(
      buildResponse({
        task_id: 7,
        task_status: "running",
        flow_draft: null,
        execution_trace: [],
        recent_errors: [],
      })
    )

    render(<ContextDrawer taskId={7} />)

    await act(async () => {
      await Promise.resolve()
    })
    expect(apiRequestMock).toHaveBeenCalledTimes(1)
    expect(screen.getByText(/当前任务状态：running/)).toBeInTheDocument()
    expect(screen.getByText(/自动刷新中/)).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })

    expect(apiRequestMock).toHaveBeenCalledTimes(2)
  })

  it("在接口返回非 2xx 时展示加载失败提示", async () => {
    apiRequestMock.mockResolvedValue(buildResponse({ detail: "boom" }, false, 500))

    render(<ContextDrawer taskId={9} />)

    await waitFor(() => {
      expect(screen.getByText("上下文加载失败")).toBeInTheDocument()
    })
  })
})
