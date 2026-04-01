/// <reference types="@testing-library/jest-dom/vitest" />
import React from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"

import { DataMakeChatSidebar } from "./datamake-chat-sidebar"
import { useDataMakeSync } from "../../../hooks/use-datamake-sync"

vi.mock("../../../hooks/use-datamake-sync", () => ({
  useDataMakeSync: vi.fn(),
}))

describe("DataMakeChatSidebar", () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it("waiting_user free_text 表单应直接提交原始文本", () => {
    const submitInteraction = vi.fn()

    vi.mocked(useDataMakeSync).mockReturnValue({
      state: {
        taskId: 42,
        status: "waiting_user",
        ticketId: "itk_123",
        question: "请确认目标环境",
        field: "datamake_reply_decision_x",
        chatResponseConfig: {
          response_contract: "free_text",
        },
      },
      messages: [],
      startChat: vi.fn(),
      submitInteraction,
    })

    render(<DataMakeChatSidebar taskId={42} />)

    fireEvent.change(
      screen.getByPlaceholderText("在此输入您的补充决策..."),
      { target: { value: "uat" } }
    )
    fireEvent.click(screen.getByText("提交并继续"))

    expect(submitInteraction).toHaveBeenCalledWith("uat")
  })
})
