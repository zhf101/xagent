import React from "react"

export function FlowDraftCanvas() {
  return (
    <div className="flex-1 bg-white relative flex items-center justify-center">
      <div className="absolute inset-0 pattern-dots text-gray-200 bg-[size:20px_20px]" />
      <div className="z-10 bg-white/80 p-6 rounded-lg border shadow-sm backdrop-blur flex flex-col items-center">
        <svg className="w-12 h-12 text-blue-500 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
        </svg>
        <h3 className="text-lg font-bold text-slate-800">FlowDraft 智能编排视图</h3>
        <p className="text-sm text-slate-500 mt-2 text-center max-w-sm">
          大模型左侧思考过程中，此处将实时绘制将要执行的探测、SQL查询和 API动作图谱节点。
        </p>
      </div>
    </div>
  )
}
