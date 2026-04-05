/// <reference types="@testing-library/jest-dom/vitest" />
import React from "react"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { I18nProvider } from "@/contexts/i18n-context"
import { MemoryJobsPanel } from "./memory-jobs-panel"

const apiRequestMock = vi.hoisted(() => vi.fn())

vi.mock("@/lib/api-wrapper", () => ({
  apiRequest: apiRequestMock,
}))

vi.mock("@/lib/utils", async () => {
  const actual = await vi.importActual<typeof import("@/lib/utils")>("@/lib/utils")
  return {
    ...actual,
    getApiUrl: () => "http://api.local",
  }
})

interface MockResponseOptions {
  ok?: boolean
  data?: unknown
}

function mockResponse({ ok = true, data = {} }: MockResponseOptions = {}) {
  return Promise.resolve({
    ok,
    json: vi.fn().mockResolvedValue(data),
  })
}

function renderPanel() {
  return render(
    <I18nProvider initialLocale="en">
      <MemoryJobsPanel />
    </I18nProvider>
  )
}

describe("MemoryJobsPanel", () => {
  beforeEach(() => {
    apiRequestMock.mockReset()
  })

  it("loads and renders memory jobs", async () => {
    apiRequestMock.mockImplementation((url: string) => {
      if (url.startsWith("http://api.local/api/memory/jobs?")) {
        return mockResponse({
          data: {
            jobs: [
              {
                id: 17,
                job_type: "extract_memories",
                status: "failed",
                priority: 50,
                payload_json: { session_id: "session-1" },
                dedupe_key: null,
                source_task_id: "task-123",
                source_session_id: "session-1",
                source_user_id: 1,
                source_project_id: "project-alpha",
                attempt_count: 2,
                max_attempts: 5,
                available_at: "2026-04-05T10:00:00Z",
                lease_until: null,
                locked_by: null,
                last_error: "extract failed",
                created_at: "2026-04-05T09:59:00Z",
                updated_at: "2026-04-05T10:01:00Z",
                started_at: "2026-04-05T10:00:10Z",
                finished_at: "2026-04-05T10:00:20Z",
              },
            ],
            total_count: 1,
            filters_used: {},
          },
        })
      }

      return Promise.reject(new Error(`Unexpected URL: ${url}`))
    })

    renderPanel()

    expect(screen.getByText("Memory Governance Jobs")).toBeInTheDocument()

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith("http://api.local/api/memory/jobs?limit=100", {
        headers: {},
      })
    })

    expect(await screen.findAllByText("extract_memories")).toHaveLength(2)
    expect(screen.getByText("#17")).toBeInTheDocument()
    expect(screen.getByText("task-123")).toBeInTheDocument()
    expect(screen.getByText("project-alpha")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument()
    expect(screen.getByText("extract failed")).toBeInTheDocument()
    expect(
      screen.getByText((_, element) => {
        return element?.tagName.toLowerCase() === "pre"
          && element.textContent?.includes('"session_id": "session-1"') === true
      })
    ).toBeInTheDocument()
  })

  it("retries failed jobs and reloads the list", async () => {
    let retried = false

    apiRequestMock.mockImplementation((url: string, options?: RequestInit) => {
      if (url.startsWith("http://api.local/api/memory/jobs?")) {
        return mockResponse({
          data: {
            jobs: [
              {
                id: 17,
                job_type: "extract_memories",
                status: retried ? "succeeded" : "failed",
                priority: 50,
                payload_json: { session_id: "session-1" },
                dedupe_key: null,
                source_task_id: "task-123",
                source_session_id: "session-1",
                source_user_id: 1,
                source_project_id: "project-alpha",
                attempt_count: retried ? 3 : 2,
                max_attempts: 5,
                available_at: "2026-04-05T10:00:00Z",
                lease_until: null,
                locked_by: null,
                last_error: retried ? null : "extract failed",
                created_at: "2026-04-05T09:59:00Z",
                updated_at: "2026-04-05T10:01:00Z",
                started_at: "2026-04-05T10:00:10Z",
                finished_at: "2026-04-05T10:00:20Z",
              },
            ],
            total_count: 1,
            filters_used: {},
          },
        })
      }

      if (url === "http://api.local/api/memory/jobs/17/retry") {
        retried = true
        expect(options).toMatchObject({
          method: "POST",
          headers: {},
        })
        return mockResponse({ data: { ok: true } })
      }

      return Promise.reject(new Error(`Unexpected URL: ${url}`))
    })

    renderPanel()

    const retryButton = await screen.findByRole("button", { name: "Retry" })
    fireEvent.click(retryButton)

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith("http://api.local/api/memory/jobs/17/retry", {
        method: "POST",
        headers: {},
      })
    })

    await waitFor(() => {
      expect(screen.getAllByText("succeeded")).toHaveLength(2)
    })

    expect(screen.getByText("3/5")).toBeInTheDocument()
  })
})
