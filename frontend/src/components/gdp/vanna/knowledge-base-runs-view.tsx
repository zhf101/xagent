"use client"

import React, { useState } from "react"
import { Play, History, Search, CheckCircle2, XCircle, Loader2, MessageSquare, Database, ChevronRight, User, Clock, Terminal } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

export function KnowledgeBaseRunsView() {
  const [activeTab, setActiveTab] = useState("ask")

  return (
    <div className="flex flex-col h-[calc(100vh-112px)] w-full overflow-hidden">
      
      {/* Sub Header */}
      <div className="bg-background border-b px-8 py-3 shrink-0 flex items-center justify-between shadow-sm z-10">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-auto">
          <TabsList className="bg-muted/50 p-1 h-9 rounded-xl">
            <TabsTrigger value="ask" className="text-[10px] font-black uppercase px-4 rounded-lg gap-2">
              <MessageSquare className="w-3 h-3" /> Ask 记录
            </TabsTrigger>
            <TabsTrigger value="harvest" className="text-[10px] font-black uppercase px-4 rounded-lg gap-2">
              <Database className="w-3 h-3" /> 采集记录
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex items-center gap-2">
          <Input placeholder="按 ID 或问题搜索..." className="h-8 text-xs w-48 rounded-lg bg-zinc-50/50" />
        </div>
      </div>

      <main className="flex-1 overflow-auto p-10">
        <div className="max-w-7xl mx-auto space-y-8">
          
          <div className="rounded-[2rem] border shadow-sm overflow-hidden bg-card">
            {activeTab === "ask" ? (
              <Table>
                <TableHeader className="bg-muted/30">
                  <TableRow className="hover:bg-transparent border-none">
                    <TableHead className="w-16 text-[10px] font-black uppercase">Run ID</TableHead>
                    <TableHead className="text-[10px] font-black uppercase min-w-[300px]">用户问题 (Question)</TableHead>
                    <TableHead className="text-[10px] font-black uppercase text-center">状态</TableHead>
                    <TableHead className="text-[10px] font-black uppercase">SQL 置信度</TableHead>
                    <TableHead className="text-[10px] font-black uppercase">运行时间</TableHead>
                    <TableHead className="w-12 text-right"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[
                    { id: 1024, question: "查询近一个月销售额最高的前10名客户", mode: "auto_run", status: "executed", confidence: 0.98, user: "admin", time: "2026-04-03 14:20" },
                    { id: 1023, question: "列出所有的金牌供应商", mode: "preview", status: "generated", confidence: 0.85, user: "admin", time: "2026-04-03 14:15" },
                    { id: 1022, question: "错误的表名查询测试", mode: "auto_run", status: "failed", confidence: 0.45, user: "test_user", time: "2026-04-03 13:50" },
                  ].map(run => (
                    <TableRow key={run.id} className="group border-border/40 hover:bg-muted/20 cursor-pointer">
                      <TableCell className="font-mono text-[10px] text-muted-foreground">#{run.id}</TableCell>
                      <TableCell>
                        <div className="text-xs font-bold truncate max-w-[400px]">{run.question}</div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center justify-center gap-1.5">
                          {run.status === "executed" ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500"/> : <XCircle className="w-3.5 h-3.5 text-rose-500"/>}
                          <span className="text-[9px] font-black uppercase">{run.status}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <div className="w-12 h-1 rounded-full bg-muted overflow-hidden">
                            <div className={cn("h-full", run.confidence > 0.9 ? "bg-emerald-500" : "bg-amber-500")} style={{ width: `${run.confidence * 100}%` }} />
                          </div>
                          <span className="text-[10px] font-mono font-black">{(run.confidence * 100).toFixed(0)}%</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-[10px] font-bold text-muted-foreground uppercase">{run.time}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="icon" className="h-8 w-8 opacity-0 group-hover:opacity-100"><ChevronRight className="w-4 h-4"/></Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : null}
          </div>
        </div>
      </main>
    </div>
  )
}
