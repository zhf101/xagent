/// <reference types="@testing-library/jest-dom/vitest" />
import React from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"

import { useDataMakeSync } from "./use-datamake-sync"

function TestHarness({ taskId }: { taskId?: number }) {
  const { state, messages, startChat, submitInteraction } = useDataMakeSync(taskId)

  return (
    <div>
      <div data-testid="status">{state.status}</div>
      <div data-testid="question">{state.question || ""}</div>
      <div data-testid="field">{state.field || ""}</div>
      <div data-testid="ticket-id">{state.ticketId || ""}</div>
      <div data-testid="approval-id">{state.approvalId || ""}</div>
      <div data-testid="task-id">{state.taskId ?? ""}</div>
      <div data-testid="messages">{messages.length}</div>
      <button onClick={() => void startChat("创建订单")}>start</button>
      <button
        onClick={() => void submitInteraction({ target_environment: "uat" })}
      >
        interact
      </button>
    </div>
  )
}

function buildJsonResponse(data: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(data),
  } as unknown as Response
}

describe("useDataMakeSync", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    cleanup()
  })

  it("startChat 成功后会进入 waiting_user 并写入问题", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      buildJsonResponse({
        task_id: 101,
        result: {
          status: "waiting_user",
          question: "请确认目标环境",
          field: "interaction_reply",
          chat_response: { form_kind: "question" },
        },
      })
    )

    render(<TestHarness />)
    fireEvent.click(screen.getByText("start"))

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("waiting_user")
    })

    expect(screen.getByTestId("task-id")).toHaveTextContent("101")
    expect(screen.getByTestId("question")).toHaveTextContent("请确认目标环境")
    expect(screen.getByTestId("field")).toHaveTextContent("interaction_reply")
    expect(screen.getByTestId("messages")).toHaveTextContent("2")
  })

  it("startChat 遇到非 2xx 时会进入 failed 并展示后端错误", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      buildJsonResponse(
        {
          detail: "造数引擎执行异常: upstream exploded",
        },
        false,
        500
      )
    )

    render(<TestHarness />)
    fireEvent.click(screen.getByText("start"))

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("failed")
    })

    expect(screen.getByTestId("question")).toHaveTextContent(
      "造数引擎执行异常: upstream exploded"
    )
  })

  it("submitInteraction 成功后会进入 completed", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        buildJsonResponse({
          task_id: 101,
          result: {
            status: "waiting_user",
            question: "请确认目标环境",
            field: "interaction_reply",
          },
        })
      )
      .mockResolvedValueOnce(
        buildJsonResponse({
          task_id: 101,
          result: {
            status: "completed",
          },
        })
      )

    render(<TestHarness />)
    fireEvent.click(screen.getByText("start"))

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("waiting_user")
    })

    fireEvent.click(screen.getByText("interact"))

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("completed")
    })
  })

  it("带 taskId 挂载时会恢复 waiting_user 暂停态", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      buildJsonResponse({
        task_id: 42,
        task_status: "paused",
        flow_draft: null,
        execution_trace: [],
        recent_errors: [],
        pending_resume: {
          status: "waiting_user",
          question: "请确认目标环境",
          field: "datamake_reply_decision_x",
          ticket_id: "itk_123",
          chat_response: {
            title: "需要补充信息",
            summary: "当前信息不足，需要用户补充回复。",
            response_contract: "free_text",
          },
        },
      })
    )

    render(<TestHarness taskId={42} />)

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("waiting_user")
    })

    expect(screen.getByTestId("task-id")).toHaveTextContent("42")
    expect(screen.getByTestId("field")).toHaveTextContent("datamake_reply_decision_x")
    expect(screen.getByTestId("ticket-id")).toHaveTextContent("itk_123")
    expect(screen.getByTestId("question")).toHaveTextContent("请确认目标环境")
    expect(screen.getByTestId("messages")).toHaveTextContent("1")
  })
})
