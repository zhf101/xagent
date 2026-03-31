import { afterEach, describe, expect, it, vi } from "vitest"

import { getApiUrl, getWsUrl } from "./utils"

describe("API / WebSocket 地址回退策略", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    delete process.env.NEXT_PUBLIC_API_URL
    delete process.env.NEXT_PUBLIC_WS_URL
  })

  it("优先使用显式配置的 NEXT_PUBLIC_API_URL / NEXT_PUBLIC_WS_URL", () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.example.com/"
    process.env.NEXT_PUBLIC_WS_URL = "ws://ws.example.com/"

    expect(getApiUrl()).toBe("http://api.example.com")
    expect(getWsUrl()).toBe("ws://ws.example.com")
  })

  it("通过非 localhost 主机访问页面时，会把 loopback API / WS 地址改写成当前页面主机", () => {
    process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000/"
    process.env.NEXT_PUBLIC_WS_URL = "ws://127.0.0.1:8000/"

    vi.stubGlobal("window", {
      location: {
        hostname: "192.168.31.50",
        host: "192.168.31.50:3000",
        protocol: "http:",
      },
    })

    expect(getApiUrl()).toBe("http://192.168.31.50:8000")
    expect(getWsUrl()).toBe("ws://192.168.31.50:8000")
  })

  it("本地开发时在缺省配置下回退到 8000 端口后端", () => {
    vi.stubGlobal("window", {
      location: {
        hostname: "localhost",
        host: "localhost:3000",
        protocol: "http:",
      },
    })

    expect(getApiUrl()).toBe("http://localhost:8000")
    expect(getWsUrl()).toBe("ws://localhost:8000")
  })

  it("非本地域名在缺省配置下保持同域 WebSocket 基址推导", () => {
    vi.stubGlobal("window", {
      location: {
        hostname: "xagent.example.com",
        host: "xagent.example.com",
        protocol: "https:",
      },
    })

    expect(getApiUrl()).toBe("")
    expect(getWsUrl()).toBe("wss://xagent.example.com")
  })
})
