/// <reference types="@testing-library/jest-dom/vitest" />
import React, { useState } from "react"
import { act, cleanup, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useWebSocket } from "./use-websocket"

const refreshTokenMock = vi.hoisted(() => vi.fn(async () => false))

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({
    token: "auth-token",
    refreshToken: refreshTokenMock,
  }),
}))

vi.mock("@/lib/utils", async () => {
  const actual = await vi.importActual<typeof import("@/lib/utils")>("@/lib/utils")
  return {
    ...actual,
    getWsUrl: () => "ws://example.test",
    getApiUrl: () => "http://example.test",
  }
})

class MockWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  static instances: MockWebSocket[] = []

  readyState = MockWebSocket.CONNECTING
  url: string
  protocol = ""
  extensions = ""
  sentMessages: string[] = []
  onopen: ((event: Event) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  send(message: string) {
    this.sentMessages.push(message)
  }

  close(code = 1000, reason = "") {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.({
      code,
      reason,
      wasClean: true,
      target: this,
    } as unknown as CloseEvent)
  }

  emitOpen() {
    this.readyState = MockWebSocket.OPEN
    this.onopen?.(new Event("open"))
  }

  emitMessage(payload: unknown) {
    this.onmessage?.({
      data: JSON.stringify(payload),
    } as unknown as MessageEvent)
  }
}

function HookHarness({ withCallback }: { withCallback: boolean }) {
  const [callbackCount, setCallbackCount] = useState(0)
  const { isConnected, lastMessage } = useWebSocket({
    taskId: 42,
    onMessage: withCallback
      ? () => {
          setCallbackCount(count => count + 1)
        }
      : undefined,
  })

  return (
    <div>
      <span data-testid="connected">{isConnected ? "yes" : "no"}</span>
      <span data-testid="callback-count">{callbackCount}</span>
      <span data-testid="last-message">{lastMessage?.type ?? "none"}</span>
    </div>
  )
}

describe("useWebSocket", () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal("WebSocket", MockWebSocket)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it("uses the onMessage callback without forcing lastMessage state updates", async () => {
    render(<HookHarness withCallback />)

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1)
    })

    act(() => {
      MockWebSocket.instances[0].emitOpen()
    })

    await waitFor(() => {
      expect(screen.getByTestId("connected")).toHaveTextContent("yes")
    })

    act(() => {
      MockWebSocket.instances[0].emitMessage({
        type: "trace_event",
        data: {},
        timestamp: "2026-04-06T00:00:00.000Z",
      })
    })

    await waitFor(() => {
      expect(screen.getByTestId("callback-count")).toHaveTextContent("1")
    })

    expect(screen.getByTestId("last-message")).toHaveTextContent("none")
    expect(MockWebSocket.instances).toHaveLength(1)
  })

  it("stores lastMessage when no onMessage callback is provided", async () => {
    render(<HookHarness withCallback={false} />)

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1)
    })

    act(() => {
      MockWebSocket.instances[0].emitOpen()
      MockWebSocket.instances[0].emitMessage({
        type: "trace_event",
        data: {},
        timestamp: "2026-04-06T00:00:00.000Z",
      })
    })

    await waitFor(() => {
      expect(screen.getByTestId("last-message")).toHaveTextContent("trace_event")
    })
  })
})
