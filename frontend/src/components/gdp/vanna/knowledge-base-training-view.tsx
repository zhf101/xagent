"use client"

import React, { useState } from "react"
import { BookOpen, FileCode, MessageSquare, Search, Filter, Plus, ChevronRight, CheckCircle2, AlertCircle, Clock, User, ExternalLink, MoreVertical } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"

const MOCK_TRAINING_ITEMS: any[] = [
  { id: 1, entry_code: "TS_001", type: "schema_summary", title: "crm_users 表结构摘要", schema_name: "public", table_name: "crm_users", lifecycle_status: "published", quality_status: "verified", source_kind: "bootstrap_schema", created_at: "2026-04-01", updated_at: "2026-04-02" },
  { id: 2, entry_code: "QS_001", type: "question_sql", title: "查询近一个月销售额最高的前10名客户", table_name: "crm_orders", lifecycle_status: "published", quality_status: "verified", source_kind: "manual", created_at: "2026-04-02", updated_at: "2026-04-02" },
  { id: 3, entry_code: "DC_001", type: "documentation", title: "客户分级定义说明", lifecycle_status: "candidate", quality_status: "unverified", source_kind: "manual", created_at: "2026-04-03", updated_at: "2026-04-03" },
]

export function KnowledgeBaseTrainingView() {
  const [activeTab, setActiveTab] = useState<string>("schema_summary")
  const [selectedItemId, setSelectedTableId] = useState<number>(1)
  const selectedItem = MOCK_TRAINING_ITEMS.find(i => i.id === selectedItemId)

  return (
    <div className="flex flex-col h-[calc(100vh-112px)] w-full overflow-hidden">
      
      {/* Sub Tabs */}
      <div className="bg-background border-b px-8 py-3 shrink-0 flex items-center justify-between shadow-sm z-10">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-auto">
          <TabsList className="bg-muted/50 p-1 h-9 rounded-xl border border-border/40">
            <TabsTrigger value="schema_summary" className="text-[10px] font-black uppercase px-4 rounded-lg gap-2">
              <FileCode className="w-3 h-3" /> Schema Summary
            </TabsTrigger>
            <TabsTrigger value="question_sql" className="text-[10px] font-black uppercase px-4 rounded-lg gap-2">
              <MessageSquare className="w-3 h-3" /> Question SQL
            </TabsTrigger>
            <TabsTrigger value="documentation" className="text-[10px] font-black uppercase px-4 rounded-lg gap-2">
              <BookOpen className="w-3 h-3" /> Documentation
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex items-center gap-3">
          <Button size="sm" className="h-8 rounded-full text-[10px] font-black uppercase bg-primary px-4 shadow-md">
            <Plus className="w-3 h-3 mr-1.5" /> 新建知识
          </Button>
        </div>
      </div>

      <main className="flex-1 flex overflow-hidden">
        
        {/* Left Column: Knowledge List */}
        <aside className="w-96 border-r bg-card flex flex-col shrink-0">
          <div className="p-5 border-b">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground opacity-50" />
              <Input placeholder="搜索知识标题、内容..." className="pl-9 h-9 text-xs rounded-xl bg-zinc-50/50" />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-1">
            {MOCK_TRAINING_ITEMS.filter(i => i.type === activeTab).map(item => (
              <button
                key={item.id}
                onClick={() => setSelectedTableId(item.id)}
                className={cn(
                  "w-full text-left p-4 rounded-[1.5rem] transition-all flex flex-col gap-2 border border-transparent group",
                  selectedItemId === item.id 
                    ? "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800 shadow-md ring-1 ring-black/5" 
                    : "hover:bg-muted/50"
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className={cn("text-xs font-black leading-tight line-clamp-2", selectedItemId === item.id ? "text-primary" : "text-foreground")}>
                    {item.title}
                  </span>
                  <Badge variant="outline" className={cn(
                    "text-[8px] px-1 h-4 shrink-0 uppercase font-black",
                    item.lifecycle_status === "published" ? "bg-emerald-500/10 text-emerald-600 border-emerald-200/50" : "bg-amber-500/10 text-amber-600 border-amber-200/50"
                  )}>
                    {item.lifecycle_status}
                  </Badge>
                </div>
                <div className="flex items-center justify-between text-[10px] text-muted-foreground font-bold">
                  <span className="font-mono opacity-60">{item.entry_code}</span>
                  <span>{item.updated_at}</span>
                </div>
              </button>
            ))}
          </div>
        </aside>

        {/* Right Column: Knowledge Details */}
        <section className="flex-1 flex flex-col overflow-hidden bg-white dark:bg-zinc-950">
          {selectedItem ? (
            <>
              <div className="p-10 border-b shrink-0 space-y-8 bg-card/20">
                <div className="flex items-start justify-between">
                  <div className="space-y-3">
                    <div className="flex items-center gap-3">
                      <Badge className="px-2 py-0 text-[10px] font-black uppercase bg-primary/10 text-primary border-none">{selectedItem.type.replace("_", " ")}</Badge>
                      <span className="text-[10px] font-mono font-bold text-muted-foreground tracking-widest">{selectedItem.entry_code}</span>
                    </div>
                    <h2 className="text-3xl font-black tracking-tight leading-tight max-w-2xl">{selectedItem.title}</h2>
                  </div>
                  <div className="flex items-center gap-3">
                    <Button variant="outline" size="sm" className="rounded-full h-9 px-5 text-xs font-bold bg-background">编辑</Button>
                    <Button variant="ghost" size="icon" className="rounded-full h-9 w-9"><MoreVertical className="w-4 h-4" /></Button>
                  </div>
                </div>

                <div className="grid grid-cols-4 gap-8 p-8 rounded-[2.5rem] bg-zinc-50 dark:bg-zinc-900 border-2 border-dashed border-zinc-200/50 dark:border-zinc-800">
                  <div className="space-y-1.5">
                    <div className="text-[9px] font-black text-muted-foreground uppercase tracking-[0.2em] flex items-center gap-2"><Clock className="w-3 h-3 opacity-50"/> Lifecycle</div>
                    <div className="text-xs font-black capitalize">{selectedItem.lifecycle_status}</div>
                  </div>
                  <div className="space-y-1.5">
                    <div className="text-[9px] font-black text-muted-foreground uppercase tracking-[0.2em] flex items-center gap-2"><CheckCircle2 className="w-3 h-3 opacity-50"/> Quality</div>
                    <div className="text-xs font-black flex items-center gap-2">
                      <span className={cn("w-1.5 h-1.5 rounded-full", selectedItem.quality_status === "verified" ? "bg-emerald-500" : "bg-amber-500")} />
                      <span className="capitalize">{selectedItem.quality_status}</span>
                    </div>
                  </div>
                  <div className="space-y-1.5 text-right col-span-2">
                    <div className="text-[9px] font-black text-muted-foreground uppercase tracking-[0.2em]">Source Origin</div>
                    <div className="text-xs font-black opacity-60 uppercase">{selectedItem.source_kind.replace("_", " ")}</div>
                  </div>
                </div>
              </div>

              <div className="flex-1 overflow-auto p-10 max-w-5xl mx-auto w-full">
                <div className="space-y-10">
                  {selectedItem.type === "question_sql" && (
                    <>
                      <div className="space-y-4">
                        <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-muted-foreground">User Question Context</h3>
                        <div className="p-8 rounded-[2rem] bg-zinc-50 border-2 border-zinc-100 text-lg font-bold leading-relaxed italic shadow-inner">
                          "{selectedItem.title}？"
                        </div>
                      </div>
                      <div className="space-y-4">
                        <div className="flex items-center justify-between">
                          <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-muted-foreground">Verified SQL Statement</h3>
                          <Badge variant="outline" className="text-[9px] font-mono bg-zinc-900 text-zinc-400 border-none">SQL</Badge>
                        </div>
                        <div className="p-8 rounded-[2.5rem] bg-zinc-900 text-zinc-100 font-mono text-sm leading-relaxed shadow-2xl relative overflow-hidden ring-8 ring-zinc-900/5">
                          <pre className="whitespace-pre-wrap break-all">SELECT * FROM crm_orders {"\n"}WHERE total_amount {">"} 1000 {"\n"}ORDER BY created_at DESC {"\n"}LIMIT 10;</pre>
                          <Button variant="ghost" size="icon" className="absolute top-4 right-4 text-zinc-500 hover:text-white hover:bg-zinc-800 rounded-full"><ExternalLink className="w-4 h-4"/></Button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </>
          ) : null}
        </section>

      </main>
    </div>
  )
}
