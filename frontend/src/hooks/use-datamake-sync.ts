import { useCallback, useEffect, useState } from "react"

import { apiRequest } from "@/lib/api-wrapper"
import { getApiUrl } from "@/lib/utils"

export type DataMakeStatus =
  | "idle"
  | "running"
  | "waiting_user"
  | "waiting_human"
  | "completed"
  | "failed"
  | "error"

export interface DataMakeState {
  taskId: number | null
  status: DataMakeStatus
  ticketId?: string
  approvalId?: string
  question?: string
  field?: string
  chatResponseConfig?: any // for dynamic form rendering
}

interface DataMakePendingResume {
  status?: string
  ticket_id?: string
  approval_id?: string
  question?: string
  field?: string
  chat_response?: any
}

interface DataMakeContextSnapshot {
  task_id: number
  task_status?: string
  pending_resume?: DataMakePendingResume | null
}

function normalizeDataMakeStatus(status: unknown): DataMakeStatus {
  if (
    status === "idle" ||
    status === "running" ||
    status === "waiting_user" ||
    status === "waiting_human" ||
    status === "completed" ||
    status === "failed" ||
    status === "error"
  ) {
    return status
  }
  if (status === "paused") {
    return "idle"
  }
  return "error"
}

async function parseDataMakeResponse(res: Response) {
  let data: any = null

  try {
    data = await res.json()
  } catch {
    data = null
  }

  if (!res.ok) {
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : `HTTP ${res.status}`
    throw new Error(detail)
  }

  return data
}

function extractErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message
  }
  return "造数任务执行失败，请稍后重试。"
}

function buildStateFromResult(
  previous: DataMakeState,
  taskId: number,
  result: any
): DataMakeState {
  const status = normalizeDataMakeStatus(result?.status)
  return {
    ...previous,
    taskId,
    status,
    ticketId: result?.ticket_id,
    approvalId: result?.approval_id,
    question: result?.question,
    field: result?.field,
    chatResponseConfig: result?.chat_response,
  }
}

function buildStateFromContext(
  previous: DataMakeState,
  snapshot: DataMakeContextSnapshot
): DataMakeState {
  const pending = snapshot.pending_resume
  if (pending?.status === "waiting_user" || pending?.status === "waiting_human") {
    return {
      ...previous,
      taskId: snapshot.task_id,
      status: pending.status,
      ticketId: pending.ticket_id,
      approvalId: pending.approval_id,
      question: pending.question,
      field: pending.field,
      chatResponseConfig: pending.chat_response,
    }
  }

  return {
    ...previous,
    taskId: snapshot.task_id,
    status: normalizeDataMakeStatus(snapshot.task_status),
  }
}

function formatReplyMessage(reply: unknown): string {
  if (typeof reply === "string") {
    return reply
  }
  return JSON.stringify(reply)
}

export function useDataMakeSync(initialTaskId?: number) {
  const [state, setState] = useState<DataMakeState>({
    taskId: initialTaskId || null,
    status: "idle",
  })
  
  const [messages, setMessages] = useState<any[]>([])

  useEffect(() => {
    if (!initialTaskId) {
      return
    }

    let cancelled = false

    async function hydrateTaskState() {
      try {
        const res = await apiRequest(
          `${getApiUrl()}/api/v1/datamake/tasks/${initialTaskId}/context`
        )
        const data = (await parseDataMakeResponse(res)) as DataMakeContextSnapshot

        if (cancelled) {
          return
        }

        setState(previous => buildStateFromContext(previous, data))

        const pendingQuestion = data.pending_resume?.question
        if (pendingQuestion) {
          setMessages(previous => {
            if (
              previous.some(
                message =>
                  message.role === "assistant" && message.content === pendingQuestion
              )
            ) {
              return previous
            }
            return [...previous, { role: "assistant", content: pendingQuestion }]
          })
        }
      } catch (error) {
        console.error(error)
        if (!cancelled) {
          setState(previous => ({
            ...previous,
            taskId: initialTaskId ?? null,
            status: "failed",
            question: extractErrorMessage(error),
          }))
        }
      }
    }

    void hydrateTaskState()

    return () => {
      cancelled = true
    }
  }, [initialTaskId])
  
  const startChat = useCallback(async (input: string, taskId?: number) => {
    setState(s => ({ ...s, status: "running" }))
    // Optimistic UI update
    setMessages(prev => [...prev, { role: "user", content: input }])
    
    try {
      const res = await fetch("/api/v1/datamake/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          task_id: taskId || state.taskId, 
          input 
        })
      })
      const data = await parseDataMakeResponse(res)
      
      setState(s => buildStateFromResult(s, data.task_id, data.result))

      if (data.result?.question) {
        setMessages(prev => [...prev, { role: "assistant", content: data.result.question }])
      }

    } catch (error) {
      console.error(error)
      setState(s => ({
        ...s,
        status: "failed",
        question: extractErrorMessage(error),
      }))
    }
  }, [state.taskId])

  const submitInteraction = useCallback(async (reply: any) => {
    if (!state.taskId || !state.field) return
    const currentTaskId = state.taskId
    
    setState(s => ({ ...s, status: "running" }))
    setMessages(prev => [...prev, { role: "user", content: formatReplyMessage(reply) }])
    
    try {
      const res = await fetch("/api/v1/datamake/interact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          task_id: currentTaskId, 
          ticket_id: state.ticketId,
          approval_id: state.approvalId,
          field: state.field,
          reply
        })
      })
      const data = await parseDataMakeResponse(res)
      
      setState(s => buildStateFromResult(s, currentTaskId, data.result))

      if (data.result?.question) {
        setMessages(prev => [...prev, { role: "assistant", content: data.result.question }])
      }

    } catch (error) {
      console.error(error)
      setState(s => ({
        ...s,
        status: "failed",
        question: extractErrorMessage(error),
      }))
    }
  }, [state])

  return {
    state,
    messages,
    startChat,
    submitInteraction
  }
}
