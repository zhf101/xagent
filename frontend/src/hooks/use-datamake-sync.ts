import { useState, useCallback, useRef } from "react"

export type DataMakeStatus = "idle" | "running" | "waiting_user" | "waiting_human" | "completed" | "failed"

export interface DataMakeState {
  taskId: number | null
  status: DataMakeStatus
  ticketId?: string
  approvalId?: string
  question?: string
  field?: string
  chatResponseConfig?: any // for dynamic form rendering
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
      const data = await res.json()
      
      const status = data.result?.status
      setState(s => ({
        ...s,
        taskId: data.task_id,
        status: status || "completed",
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
      setState(s => ({ ...s, status: "failed" }))
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
      const data = await res.json()
      
      const status = data.result?.status
      setState(s => ({
        ...s,
        status: status || "completed",
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
      setState(s => ({ ...s, status: "failed" }))
    }
  }, [state])

  return {
    state,
    messages,
    startChat,
    submitInteraction
  }
}
