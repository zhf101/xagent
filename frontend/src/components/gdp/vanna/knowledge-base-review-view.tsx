"use client"

import React, { useState } from "react"
import { CheckSquare, CheckCircle2, XCircle, Archive, Edit3, MessageSquare, BookOpen, FileCode, AlertCircle, User, Clock, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

const MOCK_CANDIDATES = [
  { id: 1, type: "question_sql", title: "查询所有金牌客户的联系人", source: "ask_run", score: 95, created_at: "2026-04-03 10:00" },
  { id: 2, type: "schema_summary", title: "crm_orders 结构摘要更新", source: "auto_train", score: 88, created_at: "2026-04-03 11:20" },
  { id: 3, type: "documentation", title: "关于退款流程的补充说明", source: "manual", score: 100, created_at: "2026-04-03 14:05" },
]

export function KnowledgeBaseReviewView() {
  const [selectedId, setSelectedId] = useState<number>(1)
  const selected = MOCK_CANDIDATES.find(c => c.id === selectedId)

  return (
    <div className="flex h-[calc(100vh-112px)] w-full overflow-hidden animate-in slide-in-from-right duration-500">
      
      {/* Left Column: Candidate List */}
      <aside className="w-96 border-r bg-card flex flex-col shrink-0 shadow-sm">
        <div className="p-6 border-b space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-[10px] font-black uppercase tracking-widest text-muted-foreground">Candidate Pool</h3>
            <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-600 border-amber-500/20">{MOCK_CANDIDATES.length} Pending</Badge>
          </div>
          <Input placeholder="筛选候评条目..." className="h-10 text-xs rounded-xl bg-zinc-50/50" />
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-1">
          {MOCK_CANDIDATES.map(item => (
            <button
              key={item.id}
              onClick={() => setSelectedId(item.id)}
              className={cn(
                "w-full text-left p-5 rounded-[1.5rem] transition-all flex flex-col gap-3 border border-transparent group",
                selectedId === item.id 
                  ? "bg-amber-500/5 border-amber-500/20 shadow-sm ring-1 ring-amber-500/10" 
                  : "hover:bg-muted/50"
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={cn("text-xs font-bold leading-tight line-clamp-2", selectedId === item.id ? "text-amber-700" : "text-foreground")}>
                    {item.title}
                  </span>
                </div>
              </div>
              <div className="flex items-center justify-between text-[10px] text-muted-foreground font-black uppercase tracking-tighter">
                <div className="flex items-center gap-2">
                  <span>{item.source}</span>
                  <span className="w-1 h-1 rounded-full bg-border" />
                  <span className="text-emerald-600">Score: {item.score}</span>
                </div>
              </div>
            </button>
          ))}
        </div>
      </aside>

      {/* Right Column: Review Details */}
      <section className="flex-1 flex flex-col overflow-hidden bg-white dark:bg-zinc-950">
        {selected ? (
          <>
            <div className="p-10 border-b shrink-0 flex items-center justify-between bg-zinc-50/30">
              <div className="space-y-2">
                <div className="text-[10px] font-black text-amber-600 uppercase tracking-[0.3em] mb-2 flex items-center gap-2">
                  <AlertCircle className="w-3 h-3"/> Review Required
                </div>
                <h2 className="text-3xl font-black tracking-tight">{selected.title}</h2>
              </div>
              <div className="flex items-center gap-3">
                <Button variant="outline" className="rounded-full h-11 px-6 font-black text-[10px] uppercase text-rose-600 border-rose-200">驳回</Button>
                <Button className="rounded-full h-11 px-8 font-black text-[10px] uppercase bg-emerald-600 hover:bg-emerald-700 shadow-lg shadow-emerald-500/20">确认发布</Button>
              </div>
            </div>

            <div className="flex-1 overflow-auto p-10">
              <div className="max-w-4xl space-y-10">
                <div className="p-10 rounded-[3rem] bg-zinc-50 border-2 border-zinc-100 shadow-inner font-medium leading-relaxed italic text-zinc-600">
                  {/* 这里展示 Candidate 详情 */}
                  该候选知识项的详细预览内容将在此处展示...
                </div>
              </div>
            </div>
          </>
        ) : null}
      </section>
    </div>
  )
}
