import React from "react"

export function ContextDrawer() {
  return (
    <div className="flex flex-col h-full w-96 border-l bg-slate-50 overflow-y-auto">
      <div className="p-4 border-b font-bold bg-white sticky top-0">执行上下文与审计</div>
      <div className="p-4 space-y-4">
        
        {/* Placeholder for Ledger snapshots */}
        <div className="bg-white p-3 border rounded shadow-sm">
          <h4 className="text-xs font-bold text-gray-500 mb-2 uppercase tracking-wide">Flow Draft (活动草稿)</h4>
          <pre className="text-xs overflow-x-auto bg-gray-50 p-2 rounded">
            {JSON.stringify({ target: "造订单", resource: "SQL" }, null, 2)}
          </pre>
        </div>

        <div className="bg-white p-3 border rounded shadow-sm">
          <h4 className="text-xs font-bold text-blue-500 mb-2 uppercase tracking-wide">Execution Trace (底层请求)</h4>
          <div className="border-l-2 border-green-400 pl-3 py-1">
            <div className="text-xs font-bold text-green-700">HTTP PASS</div>
            <div className="text-xs text-gray-600 mt-1">/api/v1/mock-order</div>
            <div className="text-[10px] text-gray-400 mt-1">104ms · 返回 201 Created</div>
          </div>
        </div>

      </div>
    </div>
  )
}
