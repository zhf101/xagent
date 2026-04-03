"use client"

import React, { useState } from "react"
import { Database, Search, FileText, Save, ListFilter, AlertCircle, Info, ChevronDown, CheckCircle2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

const MOCK_SCHEMAS: any[] = [
  { id: 1, schema_name: "public", table_name: "crm_users", table_comment: "客户信息主表", status: "active", column_count: 5 },
  { id: 2, schema_name: "public", table_name: "crm_orders", table_comment: "客户订单表", status: "active", column_count: 18 },
  { id: 3, schema_name: "public", table_name: "crm_logs", table_comment: "操作日志", status: "stale", column_count: 10 },
]

const MOCK_COLUMNS: any[] = [
  { id: 1, pos: 1, name: "id", type: "integer", is_pk: true, default_val: "nextval('seq')", range: "", comment: "自增主键" },
  { id: 2, pos: 2, name: "user_name", type: "varchar(100)", is_pk: false, default_val: "", range: "", comment: "客户姓名" },
  { id: 3, pos: 3, name: "status", type: "varchar(20)", is_pk: false, default_val: "'active'", range: "active, inactive, frozen", comment: "生命周期状态" },
  { id: 4, pos: 4, name: "created_at", type: "timestamp", is_pk: false, default_val: "now()", range: "", comment: "创建时间" },
  { id: 5, pos: 5, name: "vip_level", type: "integer", is_pk: false, default_val: "0", range: "0, 1, 2, 3", comment: "会员等级" },
]

export function KnowledgeBaseFactsView() {
  const [selectedTableId, setSelectedTableId] = useState<number>(1)
  const selectedTable = MOCK_SCHEMAS.find(t => t.id === selectedTableId)
  
  const [isSaving, setIsSaving] = useState(false)

  const handleSave = () => {
    setIsSaving(true)
    setTimeout(() => {
      setIsSaving(false)
      // toast.success("表结构元数据已更新")
    }, 800)
  }

  return (
    <div className="flex h-[calc(100vh-112px)] w-full overflow-hidden animate-in fade-in duration-500">
      
      {/* 1. 左侧表导航 */}
      <aside className="w-72 border-r bg-card/50 flex flex-col shrink-0">
        <div className="p-5 border-b space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-[10px] font-black uppercase tracking-widest text-muted-foreground flex items-center gap-2">
              <ListFilter className="w-3 h-3" /> 表清单
            </h3>
            <Badge variant="secondary" className="text-[9px] font-bold px-1.5 h-4">{MOCK_SCHEMAS.length}</Badge>
          </div>
          <Input placeholder="搜索表名..." className="h-9 text-xs rounded-xl bg-background border-none shadow-inner" />
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-1.5">
          {MOCK_SCHEMAS.map(table => (
            <button
              key={table.id}
              onClick={() => setSelectedTableId(table.id)}
              className={cn(
                "w-full text-left p-4 rounded-2xl transition-all flex flex-col gap-1.5 border border-transparent group",
                selectedTableId === table.id 
                  ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20 scale-[1.02]" 
                  : "hover:bg-muted/80"
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono font-black truncate">
                  {table.table_name}
                </span>
                {selectedTableId !== table.id && table.status === "stale" && (
                  <Badge variant="outline" className="text-[8px] px-1 h-4 bg-amber-500/10 text-amber-600 border-amber-200">STALE</Badge>
                )}
              </div>
              <div className={cn(
                "text-[10px] truncate italic font-medium",
                selectedTableId === table.id ? "text-primary-foreground/70" : "text-muted-foreground"
              )}>
                {table.table_comment || "未分类"}
              </div>
            </button>
          ))}
        </div>
      </aside>

      {/* 2. 中间编辑主区域 */}
      <section className="flex-1 flex flex-col overflow-hidden bg-background">
        {selectedTable ? (
          <>
            {/* 表头信息 & 批量保存 */}
            <div className="p-8 border-b shrink-0 bg-white dark:bg-zinc-950 flex items-center justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-3">
                  <Badge className="bg-primary/10 text-primary border-none text-[9px] font-black uppercase tracking-[0.2em]">Structure Facts</Badge>
                  <span className="text-[10px] font-mono font-bold text-muted-foreground opacity-60">{selectedTable.schema_name}</span>
                </div>
                <h2 className="text-3xl font-black font-mono tracking-tight flex items-center gap-3">
                  {selectedTable.table_name}
                  <Button variant="ghost" size="icon" className="h-6 w-6 rounded-full"><Info className="w-4 h-4 opacity-30" /></Button>
                </h2>
              </div>
              <div className="flex items-center gap-3">
                <Button 
                  onClick={handleSave}
                  disabled={isSaving}
                  className="rounded-full h-11 px-8 font-black text-xs uppercase tracking-widest shadow-xl shadow-primary/20"
                >
                  {isSaving ? "正在同步..." : <><Save className="w-4 h-4 mr-2" /> 保存元数据变更</>}
                </Button>
              </div>
            </div>

            {/* 编辑表格 */}
            <div className="flex-1 overflow-auto p-8">
              <div className="rounded-[2.5rem] border shadow-2xl shadow-black/5 overflow-hidden bg-card">
                <Table>
                  <TableHeader className="bg-zinc-50 dark:bg-zinc-900 border-b">
                    <TableRow className="hover:bg-transparent border-none">
                      <TableHead className="w-12 text-center text-[10px] font-black uppercase tracking-widest">#</TableHead>
                      <TableHead className="w-[200px] text-[10px] font-black uppercase tracking-widest">物理字段 (Name/Type)</TableHead>
                      <TableHead className="w-[180px] text-[10px] font-black uppercase tracking-widest text-primary">默认值 (Default)</TableHead>
                      <TableHead className="w-[220px] text-[10px] font-black uppercase tracking-widest text-primary">取值范围 (Enum/Range)</TableHead>
                      <TableHead className="min-w-[300px] text-[10px] font-black uppercase tracking-widest text-primary">业务说明 (Description)</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {MOCK_COLUMNS.map(col => (
                      <TableRow key={col.id} className="group border-zinc-100 dark:border-zinc-800 hover:bg-zinc-50/50 dark:hover:bg-zinc-900/50 transition-colors">
                        <TableCell className="text-center text-[10px] font-mono font-bold text-muted-foreground">
                          {col.pos}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col gap-1">
                            <div className="font-mono text-xs font-black flex items-center gap-2">
                              {col.is_pk && <Database className="w-3 h-3 text-amber-500" />}
                              {col.name}
                            </div>
                            <div className="text-[9px] font-mono font-black text-muted-foreground uppercase opacity-50">
                              {col.type}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Input 
                            defaultValue={col.default_val} 
                            placeholder="如: now()"
                            className="h-9 text-xs font-mono bg-zinc-50/50 border-dashed hover:border-primary/50 focus:border-primary transition-all rounded-xl"
                          />
                        </TableCell>
                        <TableCell>
                          <Input 
                            defaultValue={col.range} 
                            placeholder="逗号分隔, 如: A, B, C"
                            className="h-9 text-xs font-medium bg-zinc-50/50 border-dashed hover:border-primary/50 focus:border-primary transition-all rounded-xl"
                          />
                        </TableCell>
                        <TableCell>
                          <Textarea 
                            defaultValue={col.comment} 
                            placeholder="描述该字段在业务系统中的实际含义..."
                            className="min-h-[40px] py-2 text-xs font-medium bg-zinc-50/50 border-dashed hover:border-primary/50 focus:border-primary transition-all rounded-2xl resize-none"
                          />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* 底部提示 */}
              <div className="mt-8 flex items-center gap-3 px-6 py-4 rounded-[2rem] bg-zinc-50 dark:bg-zinc-900/50 border border-dashed border-zinc-200 dark:border-zinc-800">
                <AlertCircle className="w-4 h-4 text-primary opacity-60" />
                <p className="text-[11px] text-muted-foreground font-medium italic leading-relaxed">
                  提示：此处补充的元数据将直接注入大模型的上下文（Prompt），<span className="text-foreground font-black">“取值范围”</span> 有助于模型生成准确的 WHERE 过滤条件，<span className="text-foreground font-black">“业务说明”</span> 是解决语义歧义的关键。
                </p>
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center gap-4 text-muted-foreground animate-pulse">
            <Database className="w-12 h-12 opacity-10" />
            <p className="text-xs font-black uppercase tracking-widest opacity-20">Select a table to start mapping</p>
          </div>
        )}
      </section>

    </div>
  )
}
