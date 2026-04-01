import { useState, useCallback } from "react"

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

export function useDataMakeSync(initialTaskId?: number) {
  const [state, setState] = useState<DataMakeState>({
    taskId: initialTaskId || null,
    status: "idle",
  })
  
  const [messages, setMessages] = useState<any[]>([])
  
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
      
      const status = normalizeDataMakeStatus(data.result?.status)
      setState(s => ({
        ...s,
        taskId: data.task_id,
        status,
        ticketId: data.result?.ticket_id,
        approvalId: data.result?.approval_id,
        question: data.result?.question,
        field: data.result?.field,
        chatResponseConfig: data.result?.chat_response,
      }))

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
    
    setState(s => ({ ...s, status: "running" }))
    setMessages(prev => [...prev, { role: "user", content: JSON.stringify(reply) }])
    
    try {
      const res = await fetch("/api/v1/datamake/interact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          task_id: state.taskId, 
          ticket_id: state.ticketId,
          approval_id: state.approvalId,
          field: state.field,
          reply
        })
      })
      const data = await parseDataMakeResponse(res)
      
      const status = normalizeDataMakeStatus(data.result?.status)
      setState(s => ({
        ...s,
        status,
        ticketId: data.result?.ticket_id,
        approvalId: data.result?.approval_id,
        question: data.result?.question,
        field: data.result?.field,
        chatResponseConfig: data.result?.chat_response,
      }))

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
