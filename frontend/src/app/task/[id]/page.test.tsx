/// <reference types="@testing-library/jest-dom/vitest" />
import React from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"

import TaskDetailPage from "./page"

const apiRequestMock = vi.hoisted(() => vi.fn())
const toastSuccessMock = vi.hoisted(() => vi.fn())
const toastErrorMock = vi.hoisted(() => vi.fn())
const useAppMock = vi.hoisted(() => vi.fn())

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "6" }),
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock("@/contexts/app-context-chat", () => ({
  useApp: useAppMock,
}))

vi.mock("@/contexts/i18n-context", () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

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

vi.mock("sonner", () => ({
  toast: {
    success: toastSuccessMock,
    error: toastErrorMock,
  },
}))

vi.mock("@/components/chat/ChatMessage", () => ({
  ChatMessage: ({ content }: { content: React.ReactNode }) => <div>{content}</div>,
}))

vi.mock("@/components/chat/ChatInput", () => ({
  ChatInput: () => <div data-testid="chat-input">chat-input</div>,
}))

vi.mock("@/components/preview-sheet", () => ({
  PreviewSheet: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock("@/components/file/file-preview-content", () => ({
  FilePreviewContent: () => <div>file-preview</div>,
}))

vi.mock("@/components/chat/TokenUsageDisplay", () => ({
  TokenUsageDisplay: () => <div>token-usage</div>,
}))

vi.mock("@/components/file/task-file-manager", () => ({
  TaskFileManager: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock("@/components/layout/center-panel", () => ({
  CenterPanel: () => <div>center-panel</div>,
}))

vi.mock("@/components/file/file-preview-action-buttons", () => ({
  FilePreviewActionButtons: () => <div>file-preview-actions</div>,
}))

vi.mock("dagre", () => ({
  default: {
    graphlib: {
      Graph: class {
        setGraph() {}
        setDefaultEdgeLabel() {}
        setNode() {}
        setEdge() {}
        node() {
          return { x: 100, y: 100 }
        }
      },
    },
    layout() {},
  },
}))

function buildUseAppValue() {
  return {
    state: {
      messages: [],
      currentTask: {
        id: "6",
        title: "SQL approval task",
        status: "waiting_approval",
        description: "Run guarded SQL",
        createdAt: "2026-04-03T00:00:00Z",
        updatedAt: "2026-04-03T00:10:00Z",
        isDag: true,
        approval: {
          task_status: "waiting_approval",
          dag_phase: "waiting_approval",
          blocked_step_id: "step_sql_execute",
          blocked_action_type: "sql_execute",
          approval_request_id: 12,
          snapshot_version: 3,
          global_iteration: 5,
          pending_request: null,
          approved_request: {
            id: 12,
            task_id: 6,
            plan_id: "plan_1",
            step_id: "step_sql_execute",
            attempt_no: 1,
            approval_type: "sql_execute",
            status: "approved",
            datasource_id: "ds_prod",
            environment: "prod",
            sql_original: "DELETE FROM orders WHERE created_at < NOW() - INTERVAL '30 days';",
            sql_normalized: "delete from orders where created_at < ?",
            sql_fingerprint: "fp_123",
            operation_type: "delete",
            policy_version: "v1",
            risk_level: "high",
            risk_reasons: ["DELETE 语句", "生产环境"],
            tool_name: "sql_query",
            tool_payload: {},
            dag_snapshot_version: 3,
            resume_token: "resume_123",
            requested_by: 1,
            approved_by: 2,
            approved_at: "2026-04-03T00:08:00Z",
            reason: "approved",
            timeout_at: null,
            created_at: "2026-04-03T00:05:00Z",
            updated_at: "2026-04-03T00:08:00Z",
          },
          latest_request: {
            id: 12,
            task_id: 6,
            plan_id: "plan_1",
            step_id: "step_sql_execute",
            attempt_no: 1,
            approval_type: "sql_execute",
            status: "approved",
            datasource_id: "ds_prod",
            environment: "prod",
            sql_original: "DELETE FROM orders WHERE created_at < NOW() - INTERVAL '30 days';",
            sql_normalized: "delete from orders where created_at < ?",
            sql_fingerprint: "fp_123",
            operation_type: "delete",
            policy_version: "v1",
            risk_level: "high",
            risk_reasons: ["DELETE 语句", "生产环境"],
            tool_name: "sql_query",
            tool_payload: {},
            dag_snapshot_version: 3,
            resume_token: "resume_123",
            requested_by: 1,
            approved_by: 2,
            approved_at: "2026-04-03T00:08:00Z",
            reason: "approved",
            timeout_at: null,
            created_at: "2026-04-03T00:05:00Z",
            updated_at: "2026-04-03T00:08:00Z",
          },
          blocked_step_run: null,
          can_resume: true,
          last_resume_at: null,
          last_resume_by: null,
        },
      },
      dagExecution: null,
      steps: [],
      traceEvents: [],
      selectedStepId: null,
      isProcessing: false,
      taskId: 6,
      filePreview: {
        isOpen: false,
        fileId: "",
        fileName: "",
        content: "",
        isLoading: false,
        error: null,
        availableFiles: [],
        currentIndex: 0,
        viewMode: "preview",
      },
      isReplaying: false,
      replaySpeed: 1,
      replayProgress: 0,
      replayEvents: [],
      replayTaskId: null,
      replayScheduler: null,
      replayEventCache: [],
      planMemoryInfo: null,
      lastTaskUpdate: Date.now(),
      isHistoryLoading: false,
    },
    sendMessage: vi.fn(),
    setTaskId: vi.fn(),
    openFilePreview: vi.fn(),
    closeFilePreview: vi.fn(),
    requestStatus: vi.fn(),
    dispatch: vi.fn(),
    pauseTask: vi.fn(),
    resumeTask: vi.fn(),
  }
}

describe("TaskDetailPage approval flow", () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    apiRequestMock.mockReset()
  })

  it("renders SQL approval summary and resumes approved task", async () => {
    window.HTMLElement.prototype.scrollIntoView = vi.fn()
    useAppMock.mockReturnValue(buildUseAppValue())
    apiRequestMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ resumed: true }),
    })

    render(<TaskDetailPage />)

    expect(screen.getByText("审批已通过，可继续执行")).toBeInTheDocument()
    expect(screen.getByText("step_sql_execute")).toBeInTheDocument()
    expect(screen.getByText("ds_prod")).toBeInTheDocument()
    expect(screen.getByText(/DELETE FROM orders/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "审批通过后继续执行" }))

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith(
        "http://api.local/api/chat/task/6/resume-approved",
        expect.objectContaining({
          method: "POST",
        })
      )
    })

    expect(toastSuccessMock).toHaveBeenCalledWith("DAG 已恢复执行")
  })
})
