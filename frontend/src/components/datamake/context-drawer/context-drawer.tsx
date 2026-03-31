import React, { useEffect, useState } from "react"
import { apiRequest } from "@/lib/api-wrapper"
import { getApiUrl } from "@/lib/utils"

type ExecutionTraceItem = {
  round_id?: number
  record_id?: number
  created_at?: string | null
  observation_type?: string
  status?: string
  summary?: string | null
  error?: string | null
  action?: string | null
  action_kind?: string | null
  resource_key?: string | null
  operation_key?: string | null
  mode?: string | null
  evidence?: string[]
  facts?: {
    transport_status?: string | null
    protocol_status?: string | null
    business_status?: string | null
    http_status?: number | null
    normalizer?: string | null
  }
  data?: Record<string, unknown>
}

type RecentErrorItem = {
  event_id: string
  step_id?: string | null
  timestamp?: string | null
  error_type?: string | null
  error_message?: string | null
  round_id?: number | null
  attempt?: number | null
  retryable?: boolean | null
  stage?: string | null
  title?: string | null
  hint?: string | null
  transient?: boolean | null
}

type DataMakeContextPayload = {
  task_id: number
  task_status: string
  flow_draft: Record<string, unknown> | null
  execution_trace: ExecutionTraceItem[]
  recent_errors: RecentErrorItem[]
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "时间未知"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString("zh-CN")
}

function buildExecutionTone(item: ExecutionTraceItem): {
  border: string
  title: string
  titleColor: string
} {
  if (item.status === "success") {
    return {
      border: "border-green-400",
      title: "执行成功",
      titleColor: "text-green-700",
    }
  }
  if (item.observation_type === "blocker") {
    return {
      border: "border-amber-400",
      title: "执行阻断",
      titleColor: "text-amber-700",
    }
  }
  return {
    border: "border-red-400",
    title: "执行失败",
    titleColor: "text-red-700",
  }
}

export function ContextDrawer({ taskId }: { taskId?: number }) {
  const [context, setContext] = useState<DataMakeContextPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!taskId) {
      setContext(null)
      setError(null)
      return
    }

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    async function loadContext(showLoading: boolean) {
      if (showLoading) {
        setLoading(true)
      }
      try {
        const res = await apiRequest(`${getApiUrl()}/api/v1/datamake/tasks/${taskId}/context`)
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        const data = await res.json() as DataMakeContextPayload
        if (!cancelled) {
          setContext(data)
          setError(null)
          const shouldPoll =
            data.task_status === "running" ||
            data.recent_errors.some(item => item.retryable || item.transient)
          if (shouldPoll) {
            timer = setTimeout(() => {
              void loadContext(false)
            }, 3000)
          }
        }
      } catch (err) {
        if (!cancelled) {
          console.error("Failed to load datamake context", err)
          setError("上下文加载失败")
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadContext(true)

    return () => {
      cancelled = true
      if (timer) {
        clearTimeout(timer)
      }
    }
  }, [taskId])

  const flowDraft = context?.flow_draft
  const executionTrace = context?.execution_trace || []
  const recentErrors = context?.recent_errors || []
  const taskStatus = context?.task_status

  return (
    <div className="flex flex-col h-full w-96 border-l bg-background overflow-y-auto">
      <div className="p-4 border-b font-bold bg-white sticky top-0">
        <div>执行上下文与审计</div>
        {taskStatus && (
          <div className="mt-2 text-[11px] font-medium text-slate-500">
            当前任务状态：{taskStatus}
            {taskStatus === "running" ? " · 自动刷新中" : ""}
          </div>
        )}
      </div>
      <div className="p-4 space-y-4">
        <div className="bg-white p-3 border rounded shadow-sm">
          <h4 className="text-xs font-bold text-gray-500 mb-2 uppercase tracking-wide">Flow Draft (活动草稿)</h4>
          {loading ? (
            <div className="text-xs text-muted-foreground bg-background p-3 rounded border border-dashed">
              正在加载...
            </div>
          ) : flowDraft ? (
            <pre className="text-xs overflow-x-auto bg-background p-2 rounded border">
              {JSON.stringify(flowDraft, null, 2)}
            </pre>
          ) : (
            <div className="text-xs text-muted-foreground bg-background p-3 rounded border border-dashed">
              当前任务还没有持久化的 Flow Draft。
            </div>
          )}
        </div>

        <div className="bg-white p-3 border rounded shadow-sm">
          <h4 className="text-xs font-bold text-blue-500 mb-2 uppercase tracking-wide">Execution Trace (底层请求)</h4>
          {loading ? (
            <div className="text-xs text-slate-500 bg-blue-50 p-3 rounded border border-dashed border-blue-200">
              正在加载...
            </div>
          ) : executionTrace.length > 0 ? (
            <div className="space-y-3">
              {executionTrace.map((item) => {
                const tone = buildExecutionTone(item)
                return (
                  <div
                    key={`${item.record_id ?? "record"}-${item.round_id ?? "round"}`}
                    className={`border-l-2 ${tone.border} pl-3 py-1 bg-background rounded-r`}
                  >
                    <div className={`text-xs font-bold ${tone.titleColor}`}>{tone.title}</div>
                    <div className="text-xs text-slate-700 mt-1">
                      {item.resource_key || "unknown_resource"} / {item.operation_key || "unknown_operation"}
                    </div>
                    <div className="text-[11px] text-slate-600 mt-1 whitespace-pre-wrap">
                      {item.summary || item.error || "无摘要"}
                    </div>
                    <div className="text-[10px] text-slate-400 mt-1">
                      round {item.round_id ?? "?"} · {item.mode || "execute"} · {formatTimestamp(item.created_at)}
                    </div>
                    <div className="text-[10px] text-slate-500 mt-1">
                      transport={item.facts?.transport_status || "unknown"} · protocol={item.facts?.protocol_status || "unknown"} · business={item.facts?.business_status || "unknown"}
                      {typeof item.facts?.http_status === "number" ? ` · http=${item.facts.http_status}` : ""}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-xs text-slate-500 bg-blue-50 p-3 rounded border border-dashed border-blue-200">
              当前任务还没有真实底层执行记录。
              {taskStatus === "running" ? " 如果最近错误里显示模型重试中，说明还没走到底层资源执行阶段。" : ""}
            </div>
          )}
        </div>

        <div className="bg-white p-3 border rounded shadow-sm">
          <h4 className="text-xs font-bold text-rose-500 mb-2 uppercase tracking-wide">Recent Errors (最近错误)</h4>
          {error ? (
            <div className="text-xs text-red-600 bg-red-50 p-3 rounded border border-dashed border-red-200">
              {error}
            </div>
          ) : recentErrors.length > 0 ? (
            <div className="space-y-3">
              {recentErrors.map((item) => (
                <div
                  key={item.event_id}
                  className={`border-l-2 pl-3 py-1 rounded-r ${
                    item.transient
                      ? "border-amber-400 bg-amber-50"
                      : "border-red-400 bg-red-50"
                  }`}
                >
                  <div className={`text-xs font-bold ${item.transient ? "text-amber-700" : "text-red-700"}`}>
                    {item.title || item.error_type || "UnknownError"}
                  </div>
                  <div className={`text-[11px] mt-1 whitespace-pre-wrap ${item.transient ? "text-amber-800" : "text-red-800"}`}>
                    {item.error_message || "无错误详情"}
                  </div>
                  {item.hint && (
                    <div className={`text-[10px] mt-1 ${item.transient ? "text-amber-700" : "text-red-700"}`}>
                      {item.hint}
                    </div>
                  )}
                  <div className={`text-[10px] mt-1 ${item.transient ? "text-amber-500" : "text-red-500"}`}>
                    {item.round_id ? `round ${item.round_id} · ` : ""}
                    {item.attempt ? `attempt ${item.attempt} · ` : ""}
                    {item.retryable ? "可重试 · " : ""}
                    {formatTimestamp(item.timestamp)}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-muted-foreground bg-background p-3 rounded border border-dashed">
              当前任务没有最近错误记录。
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
