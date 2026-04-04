/// <reference types="@testing-library/jest-dom/vitest" />
import React from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"

import SystemRegistryPage from "./system-registry"

const apiRequestMock = vi.hoisted(() => vi.fn())
const authUserState = vi.hoisted(() => ({
  value: { username: "admin", is_admin: true },
}))

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({
    user: authUserState.value,
  }),
}))

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

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button {...props}>{children}</button>,
}))

vi.mock("@/components/ui/input", () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}))

vi.mock("@/components/ui/label", () => ({
  Label: ({ children }: { children: React.ReactNode }) => <label>{children}</label>,
}))

vi.mock("@/components/ui/textarea", () => ({
  Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} />,
}))

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock("@/components/ui/table", () => ({
  Table: ({ children }: { children: React.ReactNode }) => <table>{children}</table>,
  TableBody: ({ children }: { children: React.ReactNode }) => <tbody>{children}</tbody>,
  TableCell: ({ children, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) => (
    <td {...props}>{children}</td>
  ),
  TableHead: ({ children, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) => (
    <th {...props}>{children}</th>
  ),
  TableHeader: ({ children }: { children: React.ReactNode }) => <thead>{children}</thead>,
  TableRow: ({ children }: { children: React.ReactNode }) => <tr>{children}</tr>,
}))

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}))

vi.mock("@/components/ui/card", () => ({
  Card: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
  CardContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  CardHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}))

vi.mock("@/components/ui/select-radix", () => ({
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
  SelectValue: ({ placeholder }: { placeholder?: string }) => <span>{placeholder ?? ""}</span>,
}))

describe("SystemRegistryPage", () => {
  beforeEach(() => {
    apiRequestMock.mockReset()
  })

  it("shows permission hint for non-admin users", () => {
    authUserState.value = { username: "member", is_admin: false }

    render(<SystemRegistryPage />)

    expect(screen.getByText("无权限访问")).toBeInTheDocument()
    expect(
      screen.getByText("只有全局管理员可以维护 system_short 与系统角色。")
    ).toBeInTheDocument()
  })

  it("loads and renders systems for global admins", async () => {
    authUserState.value = { username: "admin", is_admin: true }
    apiRequestMock.mockImplementation((url: string) => {
      if (url.includes("/api/system-registry")) {
        return Promise.resolve({
          ok: true,
          json: vi.fn().mockResolvedValue({
            data: [
              {
                system_short: "CRM",
                display_name: "客户关系管理系统",
                description: "审批边界按 CRM 归属",
                status: "active",
                member_count: 3,
                system_admin_count: 1,
                updated_at: null,
              },
            ],
          }),
        })
      }

      if (url.includes("/api/admin/users")) {
        return Promise.resolve({
          ok: true,
          json: vi.fn().mockResolvedValue({
            users: [{ id: 1, username: "alice", is_admin: true }],
          }),
        })
      }

      return Promise.reject(new Error(`Unexpected URL: ${url}`))
    })

    render(<SystemRegistryPage />)

    expect(screen.getByText("系统管理")).toBeInTheDocument()

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith("http://api.local/api/system-registry")
      expect(apiRequestMock).toHaveBeenCalledWith("http://api.local/api/admin/users?page=1&size=100")
    })

    expect(await screen.findByText("CRM")).toBeInTheDocument()
    expect(screen.getByText("客户关系管理系统")).toBeInTheDocument()
    expect(screen.getByText("审批边界按 CRM 归属")).toBeInTheDocument()
  })
})
