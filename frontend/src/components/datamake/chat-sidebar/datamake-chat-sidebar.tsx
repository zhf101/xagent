import React, { useState } from "react"
import { useDataMakeSync } from "../../../hooks/use-datamake-sync"

export function DataMakeChatSidebar({ taskId }: { taskId?: number }) {
  const { state, messages, startChat, submitInteraction } = useDataMakeSync(taskId)
  const [inputVal, setInputVal] = useState("")

  const handleSend = () => {
    if (!inputVal.trim()) return
    startChat(inputVal)
    setInputVal("")
  }

  // Example generic form handler
  const handleInteractionSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const fd = new FormData(e.target as HTMLFormElement)
    const reply = Object.fromEntries(fd.entries())
    submitInteraction(reply)
  }

  return (
    <div className="flex flex-col h-full w-80 border-r bg-background">
      <div className="p-4 border-b font-bold shrink-0">造数交互台</div>
      
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {messages.map((m, i) => (
          <div key={i} className={`p-3 rounded-lg ${m.role === 'user' ? 'bg-blue-100 ml-4' : 'bg-white border mr-4'}`}>
            <span className="text-xs text-gray-500 font-bold block mb-1">
              {m.role === 'user' ? 'You' : 'Agent'}
            </span>
            <div className="whitespace-pre-wrap text-sm">{m.content}</div>
          </div>
        ))}

        {state.status === "running" && (
          <div className="p-3 border border-border bg-background text-sm text-muted-foreground rounded-lg animate-pulse">
            Agent 思考推导中...
          </div>
        )}

        {state.status === "waiting_user" && state.chatResponseConfig && (
          <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg shrink-0 mt-4">
            <h4 className="font-bold text-yellow-800 text-sm mb-2">需要您补充信息</h4>
            <p className="text-sm text-yellow-700 mb-4">{state.question}</p>
            <form onSubmit={handleInteractionSubmit} className="space-y-3">
              {/* This is a simple mock rendering. In real life, parse chatResponseConfig JSON schema */}
              <input 
                name="answer" 
                placeholder="在此输入您的补充决策..." 
                className="w-full text-sm p-2 border rounded" 
                required 
              />
              <button type="submit" className="w-full bg-yellow-600 text-white p-2 rounded text-sm hover:bg-yellow-700">
                提交并继续
              </button>
            </form>
          </div>
        )}

        {state.status === "waiting_human" && (
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg shrink-0 mt-4">
            <h4 className="font-bold text-red-800 text-sm mb-2">人工审批阻断</h4>
            <p className="text-sm text-red-700 mb-4">{state.question}</p>
            <form onSubmit={(e) => {
              e.preventDefault()
              submitInteraction({ approved: true, comment: "" })
            }} className="space-y-3">
              <button type="submit" className="w-full bg-red-600 text-white p-2 rounded text-sm hover:bg-red-700">
                我确认授权执行
              </button>
              <button type="button" onClick={() => submitInteraction({ approved: false })} className="w-full bg-white border text-red-600 hover:bg-red-50 p-2 rounded text-sm">
                驳回
              </button>
            </form>
          </div>
        )}

        {state.status === "error" && (
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg shrink-0 mt-4">
            <h4 className="font-bold text-red-800 text-sm mb-2">任务执行失败</h4>
            <p className="text-sm text-red-700 whitespace-pre-wrap">
              {state.question || "造数任务执行失败，请检查右侧追踪信息或稍后重试。"}
            </p>
          </div>
        )}
      </div>

      <div className="p-4 border-t bg-white shrink-0">
        <div className="flex gap-2">
          <input
            className="flex-1 p-2 border rounded text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="输入造数指令..."
            value={inputVal}
            onChange={e => setInputVal(e.target.value)}
            disabled={state.status === "running" || state.status.startsWith("waiting")}
            onKeyDown={e => {
              if (e.key === "Enter") handleSend()
            }}
          />
          <button 
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
            onClick={handleSend}
            disabled={state.status === "running" || state.status.startsWith("waiting")}
          >
            发送
          </button>
        </div>
      </div>
    </div>
  )
}
