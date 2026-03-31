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

  it("本地开发时在缺省配置下回退到 8000 端口后端", () => {
    vi.stubGlobal("window", {
      location: {
        hostname: "localhost",
      },
    })

    expect(getApiUrl()).toBe("http://localhost:8000")
    expect(getWsUrl()).toBe("ws://localhost:8000")
  })

  it("非本地域名在缺省配置下不猜测后端地址", () => {
    vi.stubGlobal("window", {
      location: {
        hostname: "xagent.example.com",
      },
    })

    expect(getApiUrl()).toBe("")
    expect(getWsUrl()).toBe("")
  })
})
