"use client"

export function formatApiErrorMessage(detail: unknown): string | null {
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim()
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map(item => {
        if (typeof item === "string") {
          return item.trim()
        }
        if (!item || typeof item !== "object") {
          return ""
        }

        const record = item as Record<string, unknown>
        const msg = typeof record.msg === "string" ? record.msg.trim() : ""
        const loc = Array.isArray(record.loc)
          ? record.loc
              .filter(part => typeof part === "string" || typeof part === "number")
              .join(".")
          : ""

        if (msg && loc) {
          return `${loc}: ${msg}`
        }
        if (msg) {
          return msg
        }
        return ""
      })
      .filter(Boolean)

    if (messages.length > 0) {
      return messages.join("；")
    }
  }

  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>

    if (typeof record.message === "string" && record.message.trim()) {
      return record.message.trim()
    }

    if (typeof record.msg === "string" && record.msg.trim()) {
      return record.msg.trim()
    }
  }

  return null
}

export function getApiErrorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    return formatApiErrorMessage((payload as { detail?: unknown }).detail) || fallback
  }
  return fallback
}

export function getApprovalSubmissionMessage(
  payload: unknown,
  fallback: string
): string {
  if (!payload || typeof payload !== "object") {
    return fallback
  }

  const record = payload as {
    message?: unknown
    data?: { status?: unknown }
  }

  if (typeof record.message === "string" && record.message.trim()) {
    return record.message.trim()
  }

  if (record.data?.status === "pending_approval") {
    return fallback
  }

  return fallback
}
