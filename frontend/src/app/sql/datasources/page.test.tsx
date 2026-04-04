/// <reference types="@testing-library/jest-dom/vitest" />
import React from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"

import SqlDataSourcesPage from "./page"

const apiRequestMock = vi.hoisted(() => vi.fn())
const pushMock = vi.hoisted(() => vi.fn())

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
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
    error: vi.fn(),
    success: vi.fn(),
  },
}))

vi.mock("@/components/datamake/database-form-dialog", () => ({
  DatabaseFormDialog: ({
    open,
    databaseId,
  }: {
    open: boolean
    databaseId?: number
  }) => <div data-testid="database-form-dialog">{open ? `open:${databaseId ?? "new"}` : "closed"}</div>,
}))

describe("SqlDataSourcesPage", () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    apiRequestMock.mockReset()
  })

  it("opens create dialog from header and empty state actions", async () => {
    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue([]),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue([]),
      })

    render(<SqlDataSourcesPage />)

    await screen.findByText("暂无 SQL 数据源")
    expect(screen.getByTestId("database-form-dialog")).toHaveTextContent("closed")

    fireEvent.click(screen.getByRole("button", { name: "新增数据源" }))
    expect(screen.getByTestId("database-form-dialog")).toHaveTextContent("open:new")

    cleanup()
    apiRequestMock.mockReset()
    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue([]),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue([]),
      })

    render(<SqlDataSourcesPage />)
    await screen.findByText("暂无 SQL 数据源")

    fireEvent.click(screen.getByRole("button", { name: "添加数据源" }))
    expect(screen.getByTestId("database-form-dialog")).toHaveTextContent("open:new")
  })

  it("opens edit dialog from a datasource row action without navigating", async () => {
    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue([
          {
            id: 7,
            name: "orders-db",
            type: "postgresql",
            read_only: true,
            status: "connected",
            table_count: 12,
            linked_asset_count: 3,
          },
        ]),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue([
          { db_type: "postgresql", display_name: "PostgreSQL" },
        ]),
      })

    render(<SqlDataSourcesPage />)

    await screen.findByText("orders-db")

    fireEvent.click(screen.getByRole("button", { name: /编辑/i }))

    await waitFor(() => {
      expect(screen.getByTestId("database-form-dialog")).toHaveTextContent("open:7")
    })
    expect(pushMock).not.toHaveBeenCalled()
  })
})
