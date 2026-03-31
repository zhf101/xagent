import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const LOCAL_DEVELOPMENT_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"])

function normalizeBaseUrl(url: string | undefined): string {
  if (!url) {
    return ""
  }
  return url.trim().replace(/\/+$/, "")
}

function isLoopbackHost(hostname: string): boolean {
  return LOCAL_DEVELOPMENT_HOSTS.has(hostname)
}

function rewriteLoopbackBaseUrlForBrowser(url: string): string {
  if (!url || typeof window === "undefined") {
    return url
  }

  try {
    const parsedUrl = new URL(url)
    const browserHostname = window.location.hostname

    // 构建阶段常把 API / WS 地址写成 localhost，方便“前端和浏览器都在同一台机器”调试。
    // 但一旦页面是通过局域网 IP、容器域名或反向代理域名访问，浏览器里的 localhost
    // 就会指向“访问者自己的机器”，从而让登录等请求直接报 Failed to fetch。
    // 这里仅在“配置值是 loopback，而当前页面 host 不是 loopback”时，把目标主机改写成
    // 当前页面所在主机，端口和协议保持不变，尽量兼容远程调试/局域网访问场景。
    if (!browserHostname || isLoopbackHost(browserHostname) || !isLoopbackHost(parsedUrl.hostname)) {
      return url
    }

    parsedUrl.hostname = browserHostname
    return normalizeBaseUrl(parsedUrl.toString())
  } catch {
    return url
  }
}

function resolveLocalBackendBaseUrl(protocol: "http" | "ws"): string {
  if (typeof window === "undefined") {
    return ""
  }

  const { hostname } = window.location
  if (!isLoopbackHost(hostname)) {
    return ""
  }

  // 本地开发（local development）场景下，前端通常跑在 3000 端口，
  // FastAPI 后端固定跑在 8000 端口。这里显式回退到 8000，
  // 避免 `getApiUrl()` / `getWsUrl()` 返回空串后把请求误发到 Next 自己的页面路由。
  return `${protocol}://${hostname}:8000`
}

function resolveSameOriginWebSocketBaseUrl(): string {
  if (typeof window === "undefined") {
    return ""
  }

  const { protocol, host } = window.location
  if (!host) {
    return ""
  }

  const wsProtocol = protocol === "https:" ? "wss" : "ws"
  return `${wsProtocol}://${host}`
}

export function getApiUrl(): string {
  const configuredApiUrl = normalizeBaseUrl(process.env.NEXT_PUBLIC_API_URL)
  if (configuredApiUrl) {
    return rewriteLoopbackBaseUrlForBrowser(configuredApiUrl)
  }

  return resolveLocalBackendBaseUrl("http")
}

export function getAuthHeaders(token: string | null): Record<string, string> {
  if (!token) return {}
  return {
    'Authorization': `Bearer ${token}`
  }
}

export function getWsUrl(): string {
  const configuredWsUrl = normalizeBaseUrl(process.env.NEXT_PUBLIC_WS_URL)
  if (configuredWsUrl) {
    return rewriteLoopbackBaseUrlForBrowser(configuredWsUrl)
  }

  const localWsUrl = resolveLocalBackendBaseUrl("ws")
  if (localWsUrl) {
    return localWsUrl
  }

  // 非本地环境默认回退到当前页面同域的 WebSocket 基址。
  // 这样可以继续兼容“前端页面 + /ws/* 反向代理到后端”的既有部署方式。
  return resolveSameOriginWebSocketBaseUrl()
}

export async function fetchWithAuth(url: string, token: string | null, options: RequestInit = {}): Promise<Response> {
  const headers = {
    ...options.headers,
    ...getAuthHeaders(token)
  }

  return fetch(url, {
    ...options,
    headers
  })
}

export function formatDate(date: Date | string): string {
  const d = new Date(date)
  return d.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 Bytes'

  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

export function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: NodeJS.Timeout | null = null

  return (...args: Parameters<T>) => {
    if (timeout) {
      clearTimeout(timeout)
    }

    timeout = setTimeout(() => {
      func(...args)
    }, wait)
  }
}

export function throttle<T extends (...args: any[]) => any>(
  func: T,
  limit: number
): (...args: Parameters<T>) => void {
  let inThrottle: boolean = false

  return (...args: Parameters<T>) => {
    if (!inThrottle) {
      func(...args)
      inThrottle = true
      setTimeout(() => {
        inThrottle = false
      }, limit)
    }
  }
}

export function generateId(): string {
  return Math.random().toString(36).substr(2, 9)
}

export function isValidUrl(url: string): boolean {
  try {
    new URL(url)
    return true
  } catch {
    return false
  }
}

export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength) + '...'
}

export function sanitizeFileName(fileName: string): string {
  return fileName.replace(/[^\w\s.-]/g, '').replace(/\s+/g, '_')
}

export function isHtmlFile(fileName: string): boolean {
  if (!fileName) return false
  const lowerName = fileName.toLowerCase()
  return lowerName.endsWith('.html') || lowerName.endsWith('.htm')
}

export function isMarkdownFile(fileName: string): boolean {
  if (!fileName) return false
  return fileName.toLowerCase().endsWith('.md')
}

export function isToggleableFile(fileName: string): boolean {
  return isHtmlFile(fileName) || isMarkdownFile(fileName)
}
