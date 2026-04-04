/// <reference types="@testing-library/jest-dom/vitest" />
import React from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, waitFor } from "@testing-library/react"

import { Sidebar } from "./sidebar"

const apiRequestMock = vi.hoisted(() => vi.fn())

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock("next/navigation", () => ({
  usePathname: () => "/task",
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({
    user: { username: "tester", is_admin: false },
    logout: vi.fn(),
  }),
}))

vi.mock("@/contexts/app-context-chat", () => ({
  useApp: () => ({
    state: {
      lastTaskUpdate: 0,
    },
  }),
}))

vi.mock("@/contexts/i18n-context", () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

vi.mock("@/lib/branding", () => ({
  getBrandingFromEnv: () => ({
    appName: "XAgent",
    logoPath: "/logo.png",
    logoAlt: "XAgent",
  }),
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
  },
}))

vi.mock("@/components/ui/confirm-dialog", () => ({
  ConfirmDialog: () => null,
}))

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock("@/components/ui/popover", () => ({
  Popover: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PopoverTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PopoverContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock("@/components/ui/search-input", () => ({
  SearchInput: ({
    value,
    onChange,
  }: {
    value: string
    onChange: (value: string) => void
  }) => <input value={value} onChange={e => onChange(e.target.value)} />,
}))

describe("Sidebar task history loading", () => {
  beforeEach(() => {
    apiRequestMock.mockReset()
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        version: "0.0.0",
        display_version: "0.0.0",
      }),
    } as unknown as Response)
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it("stops retrying task history requests after the endpoint returns 404", async () => {
    apiRequestMock.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    })

    render(<Sidebar />)

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledTimes(1)
    })

    expect(apiRequestMock).toHaveBeenCalledWith(
      "http://api.local/api/chat/tasks?exclude_agent_type=text2sql&page=1&per_page=10"
    )

    await new Promise(resolve => setTimeout(resolve, 250))

    expect(apiRequestMock).toHaveBeenCalledTimes(1)
  })

  it("renders resource links for SQL assets, SQL data sources and HTTP assets", async () => {
    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        tasks: [],
        pagination: { total_pages: 1 },
      }),
    })

    render(<Sidebar />)

    expect(await screen.findByRole("link", { name: "nav.sqlAssets" })).toHaveAttribute("href", "/knowledge-bases")
    expect(await screen.findByRole("link", { name: "nav.sqlDataSources" })).toHaveAttribute("href", "/sql/datasources")
    expect(screen.getByRole("link", { name: "nav.httpAssets" })).toHaveAttribute("href", "/gdp/http-assets")
  })
})
