/// <reference types="@testing-library/jest-dom/vitest" />
import React from "react"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

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

vi.mock("@/components/ui/select-radix", () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value?: string
    onValueChange?: (value: string) => void
    children: React.ReactNode
  }) => <div data-value={value} data-on-change={onValueChange ? "yes" : "no"}>{children}</div>,
  SelectTrigger: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button {...props}>{children}</button>,
  SelectValue: ({ placeholder }: { placeholder?: string }) => <span>{placeholder ?? ""}</span>,
  SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectItem: ({
    value,
    children,
  }: {
    value: string
    children: React.ReactNode
  }) => <option value={value}>{children}</option>,
}))

vi.mock("@/components/ui/switch", () => ({
  Switch: ({
    checked,
    onCheckedChange,
    ...props
  }: {
    checked?: boolean
    onCheckedChange?: (value: boolean) => void
  } & React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      type="checkbox"
      checked={checked}
      onChange={event => onCheckedChange?.(event.target.checked)}
      {...props}
    />
  ),
}))

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

  afterEach(() => {
    vi.useRealTimers()
    cleanup()
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
      expect(apiRequestMock).toHaveBeenCalledWith("http://api.local/api/memory/jobs?limit=20&offset=0", {
        headers: {},
      })
    })

    expect(screen.getByText("Showing 1-1 of 1 jobs")).toBeInTheDocument()
    expect(
      await screen.findAllByText((content, element) => {
        return content === "Extract memories" && element?.tagName !== "OPTION"
      })
    ).toHaveLength(2)
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
      expect(
        screen.getAllByText((content, element) => {
          return content === "Succeeded" && element?.tagName !== "OPTION"
        })
      ).toHaveLength(2)
    })

    expect(screen.getByText("3/5")).toBeInTheDocument()
  })

  it("requests the next page with updated offset", async () => {
    apiRequestMock.mockImplementation((url: string) => {
      if (url === "http://api.local/api/memory/jobs?limit=20&offset=0") {
        return mockResponse({
          data: {
            jobs: [
              {
                id: 1,
                job_type: "failed_job",
                status: "failed",
                priority: 100,
                payload_json: {},
                attempt_count: 1,
                max_attempts: 3,
                available_at: "2026-04-05T10:00:00Z",
                created_at: "2026-04-05T10:00:00Z",
                source_task_id: "task-page-1",
                source_project_id: "project-page-1",
              },
            ],
            total_count: 25,
            filters_used: {},
          },
        })
      }

      if (url === "http://api.local/api/memory/jobs?limit=20&offset=20") {
        return mockResponse({
          data: {
            jobs: [
              {
                id: 21,
                job_type: "expire_memories",
                status: "succeeded",
                priority: 100,
                payload_json: {},
                attempt_count: 1,
                max_attempts: 3,
                available_at: "2026-04-05T10:20:00Z",
                created_at: "2026-04-05T10:20:00Z",
                source_task_id: "task-page-2",
                source_project_id: "project-page-2",
              },
            ],
            total_count: 25,
            filters_used: {},
          },
        })
      }

      return Promise.reject(new Error(`Unexpected URL: ${url}`))
    })

    renderPanel()

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith("http://api.local/api/memory/jobs?limit=20&offset=0", {
        headers: {},
      })
    })

    await screen.findByText("Showing 1-20 of 25 jobs")

    const nextButton = screen.getAllByRole("button", { name: "Next" }).find(button => !button.hasAttribute("disabled"))
    expect(nextButton).toBeDefined()
    await waitFor(() => {
      expect(nextButton).toBeEnabled()
    })

    fireEvent.click(nextButton!)

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenLastCalledWith("http://api.local/api/memory/jobs?limit=20&offset=20", {
        headers: {},
      })
    })

    expect(screen.getByText("Showing 21-25 of 25 jobs")).toBeInTheDocument()
    expect(screen.getAllByText("Page 2 of 2")[0]).toBeInTheDocument()
  })

  it("auto refreshes job list when enabled", async () => {
    vi.useFakeTimers()
    let requestCount = 0

    apiRequestMock.mockImplementation((url: string) => {
      if (url.startsWith("http://api.local/api/memory/jobs?")) {
        requestCount += 1
        return mockResponse({
          data: {
            jobs: [],
            total_count: 0,
            filters_used: {},
          },
        })
      }

      return Promise.reject(new Error(`Unexpected URL: ${url}`))
    })

    await act(async () => {
      renderPanel()
      await Promise.resolve()
    })

    expect(requestCount).toBe(1)

    await act(async () => {
      vi.advanceTimersByTime(10_000)
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(requestCount).toBe(2)

    expect(screen.getAllByLabelText("Auto refresh")[0]).toBeChecked()
  })

  it("returns to the last valid page when total count shrinks", async () => {
    let pageTwoLoaded = false
    let pageSetShrunk = false

    apiRequestMock.mockImplementation((url: string) => {
      if (url === "http://api.local/api/memory/jobs?limit=20&offset=0") {
        return mockResponse({
          data: {
            jobs: [
              {
                id: 1,
                job_type: "extract_memories",
                status: "failed",
                priority: 100,
                payload_json: {},
                attempt_count: 1,
                max_attempts: 3,
                available_at: "2026-04-05T10:00:00Z",
                created_at: "2026-04-05T10:00:00Z",
                source_task_id: "task-page-1",
                source_project_id: "project-page-1",
              },
            ],
            total_count: pageSetShrunk ? 5 : 25,
            filters_used: {},
          },
        })
      }

      if (url === "http://api.local/api/memory/jobs?limit=20&offset=20") {
        if (!pageTwoLoaded) {
          pageTwoLoaded = true
          return mockResponse({
            data: {
              jobs: [
                {
                  id: 21,
                  job_type: "expire_memories",
                  status: "succeeded",
                  priority: 100,
                  payload_json: {},
                  attempt_count: 1,
                  max_attempts: 3,
                  available_at: "2026-04-05T10:20:00Z",
                  created_at: "2026-04-05T10:20:00Z",
                  source_task_id: "task-page-2",
                  source_project_id: "project-page-2",
                },
              ],
              total_count: 25,
              filters_used: {},
            },
          })
        }

        pageSetShrunk = true
        return mockResponse({
          data: {
            jobs: [],
            total_count: 5,
            filters_used: {},
          },
        })
      }

      return Promise.reject(new Error(`Unexpected URL: ${url}`))
    })

    renderPanel()

    await screen.findByText("Showing 1-20 of 25 jobs")

    const nextButton = screen.getAllByRole("button", { name: "Next" }).find(button => !button.hasAttribute("disabled"))
    expect(nextButton).toBeDefined()
    fireEvent.click(nextButton!)

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith("http://api.local/api/memory/jobs?limit=20&offset=20", {
        headers: {},
      })
    })

    expect(screen.getAllByText("Page 2 of 2")[0]).toBeInTheDocument()

    const refreshButton = screen.getAllByRole("button", { name: "Refresh" }).find(button => !button.hasAttribute("disabled"))
    expect(refreshButton).toBeDefined()
    fireEvent.click(refreshButton!)

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenLastCalledWith("http://api.local/api/memory/jobs?limit=20&offset=0", {
        headers: {},
      })
    })

    await waitFor(() => {
      expect(screen.getAllByText("Showing 1-5 of 5 jobs")[0]).toBeInTheDocument()
      expect(screen.getAllByText("Page 1 of 1")[0]).toBeInTheDocument()
    })
  })
})
