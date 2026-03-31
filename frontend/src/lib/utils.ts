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

function resolveLocalBackendBaseUrl(protocol: "http" | "ws"): string {
  if (typeof window === "undefined") {
    return ""
  }

  const { hostname } = window.location
  if (!LOCAL_DEVELOPMENT_HOSTS.has(hostname)) {
    return ""
  }

  // 本地开发（local development）场景下，前端通常跑在 3000 端口，
  // FastAPI 后端固定跑在 8000 端口。这里显式回退到 8000，
  // 避免 `getApiUrl()` / `getWsUrl()` 返回空串后把请求误发到 Next 自己的页面路由。
  return `${protocol}://${hostname}:8000`
}

export function getApiUrl(): string {
  const configuredApiUrl = normalizeBaseUrl(process.env.NEXT_PUBLIC_API_URL)
  if (configuredApiUrl) {
    return configuredApiUrl
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
    return configuredWsUrl
  }

  const localWsUrl = resolveLocalBackendBaseUrl("ws")
  if (localWsUrl) {
    return localWsUrl
  }

  // 非本地开发环境如果没有显式配置，就继续返回空串。
  // 这样生产环境可以通过反向代理（reverse proxy）走同域部署，
  // 同时也避免在未知主机上擅自猜测后端地址。
  return ""
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
