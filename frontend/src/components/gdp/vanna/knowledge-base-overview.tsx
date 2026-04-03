"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import {
  Activity,
  AlertCircle,
  BookOpen,
  CheckSquare,
  Database,
  FileCode,
  Loader2,
  Play,
  Search,
  Tag,
  ShieldCheck,
  Zap,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn, formatDate } from "@/lib/utils"

import {
  getVannaKnowledgeBase,
  listAskRuns,
  listHarvestJobs,
  listSchemaColumns,
  listSchemaTables,
  listTrainingEntries,
} from "./vanna-api"
import type {
  VannaAskRunRecord,
  VannaKnowledgeBaseRecord,
  VannaSchemaColumnRecord,
  VannaSchemaHarvestJobRecord,
  VannaSchemaTableRecord,
  VannaTrainingEntryRecord,
} from "./vanna-types"

function percent(numerator: number, denominator: number) {
  if (denominator === 0) return "0%"
  return `${Math.round((numerator / denominator) * 100)}%`
}

export function KnowledgeBaseOverview() {
  const params = useParams()
  const router = useRouter()
  const kbId = Number(params.id)

  const [loading, setLoading] = useState(true)
  const [kb, setKb] = useState<VannaKnowledgeBaseRecord | null>(null)
  const [schemaTables, setSchemaTables] = useState<VannaSchemaTableRecord[]>([])
  const [schemaColumns, setSchemaColumns] = useState<VannaSchemaColumnRecord[]>([])
  const [entries, setEntries] = useState<VannaTrainingEntryRecord[]>([])
  const [askRuns, setAskRuns] = useState<VannaAskRunRecord[]>([])
  const [harvestJobs, setHarvestJobs] = useState<VannaSchemaHarvestJobRecord[]>([])

  useEffect(() => {
    async function loadData() {
      setLoading(true)
      try {
        const kbDetail = await getVannaKnowledgeBase(kbId)
        setKb(kbDetail)
        const [tableRows, columnRows, entryRows, askRunRows, harvestJobRows] = await Promise.all([
          listSchemaTables({ kb_id: kbId }),
          listSchemaColumns({ kb_id: kbId }),
          listTrainingEntries({ kb_id: kbId }),
          listAskRuns({ kb_id: kbId }),
          listHarvestJobs({ kb_id: kbId }),
        ])
        setSchemaTables(tableRows)
        setSchemaColumns(columnRows)
        setEntries(entryRows)
        setAskRuns(askRunRows)
        setHarvestJobs(harvestJobRows)
      } catch (error) {
        toast.error("加载数据失败")
      } finally {
        setLoading(false)
      }
    }
    if (kbId) void loadData()
  }, [kbId])

  if (loading) return (
    <div className="flex h-64 w-full items-center justify-center">
      <Loader2 className="h-8 w-8 animate-spin text-primary/30" />
    </div>
  )

  if (!kb) return null

  const activeTables = schemaTables.filter(item => item.status === "active")
  const tablesWithComment = activeTables.filter(item => Boolean(item.table_comment?.trim()))
  const columnsWithComment = schemaColumns.filter(item => Boolean(item.column_comment?.trim()))
  const publishedEntries = entries.filter(item => item.lifecycle_status === "published")
  const candidateEntries = entries.filter(item => item.lifecycle_status === "candidate")
  const tableSummaryCoverageGap = Math.max(activeTables.length - publishedEntries.filter(i => i.entry_type === "schema_summary").length, 0)

  return (
    <div className="p-10 w-full animate-in fade-in duration-500">
      <div className="mx-auto grid max-w-7xl grid-cols-12 gap-10">
        
        {/* 主要统计区域 */}
        <div className="col-span-12 lg:col-span-8 space-y-10">
          <section className="space-y-6">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-sm font-black uppercase tracking-[0.2em] text-muted-foreground">
                <Zap className="h-4 w-4 text-primary" /> 健康度摘要
              </h2>
            </div>
            <div className="grid grid-cols-4 gap-6">
              {[
                { label: "活跃表数", value: activeTables.length },
                { label: "活跃字段数", value: schemaColumns.length },
                { label: "已发布训练知识", value: publishedEntries.length },
                { label: "待审核候选", value: candidateEntries.length, warn: true },
              ].map(item => (
                <div key={item.label} className="rounded-[2rem] border bg-card p-6 shadow-sm hover:shadow-md transition-shadow">
                  <div className="mb-2 text-[10px] font-black uppercase tracking-wider text-muted-foreground">
                    {item.label}
                  </div>
                  <div className={cn("text-3xl font-black", item.warn && candidateEntries.length > 0 ? "text-amber-600" : "text-foreground")}>
                    {item.value}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="space-y-6">
            <h2 className="flex items-center gap-2 text-sm font-black uppercase tracking-[0.2em] text-muted-foreground">
              <Database className="h-4 w-4" /> 结构事实覆盖
            </h2>
            <div className="grid grid-cols-3 gap-4">
              {[
                { label: "表注释覆盖率", value: percent(tablesWithComment.length, activeTables.length) },
                { label: "字段注释覆盖率", value: percent(columnsWithComment.length, schemaColumns.length) },
                { label: "活跃表占比", value: percent(activeTables.length, schemaTables.length) },
                { label: "默认值字段", value: schemaColumns.filter(i => i.default_raw).length },
                { label: "外键关联数", value: schemaColumns.filter(i => i.is_foreign_key).length },
                { label: "枚举字典数", value: schemaColumns.filter(i => i.allowed_values_json.length > 0).length },
              ].map(item => (
                <div key={item.label} className="flex items-center justify-between rounded-2xl border bg-card p-5 shadow-sm">
                  <span className="text-xs font-bold text-muted-foreground">{item.label}</span>
                  <span className="text-sm font-black">{item.value}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="space-y-6">
            <h2 className="flex items-center gap-2 text-sm font-black uppercase tracking-[0.2em] text-muted-foreground">
              <BookOpen className="h-4 w-4" /> 训练知识分布
            </h2>
            <div className="grid grid-cols-3 gap-6">
              {["schema_summary", "question_sql", "documentation"].map(type => {
                const pub = publishedEntries.filter(i => i.entry_type === type).length
                const can = candidateEntries.filter(i => i.entry_type === type).length
                return (
                  <div key={type} className="rounded-[2rem] border bg-card p-6 shadow-sm">
                    <div className="mb-4 text-[10px] font-black uppercase tracking-widest text-foreground opacity-60">
                      {type.replace("_", " ")}
                    </div>
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="text-[9px] font-black uppercase text-emerald-600 mb-1">Published</div>
                        <div className="text-2xl font-black">{pub}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-[9px] font-black uppercase text-amber-600 mb-1">Candidate</div>
                        <div className="text-2xl font-black">{can}</div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        </div>

        {/* 侧边风险/信息区域 */}
        <div className="col-span-12 lg:col-span-4 space-y-10">
          <section className="space-y-6 rounded-[2.5rem] border border-amber-500/20 bg-amber-50/30 dark:bg-amber-950/10 p-8 shadow-sm">
            <h2 className="flex items-center gap-2 text-sm font-black uppercase tracking-widest text-amber-700 dark:text-amber-500">
              <AlertCircle className="h-4 w-4" /> 治理待办
            </h2>
            <div className="space-y-6 text-sm">
              {candidateEntries.length > 0 && (
                <div className="flex items-start gap-4">
                  <div className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-amber-500 shadow-[0_0_10px_rgba(245,158,11,0.5)]" />
                  <div>
                    <div className="font-bold text-amber-900 dark:text-amber-200">{candidateEntries.length} 条候选知识待审核</div>
                    <div className="mt-1 text-xs text-amber-700/70 dark:text-amber-500/70 leading-relaxed">建议优先处理 Ask 回流样例以优化召回精度。</div>
                  </div>
                </div>
              )}
              {tableSummaryCoverageGap > 0 && (
                <div className="flex items-start gap-4">
                  <div className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-amber-500 shadow-[0_0_10px_rgba(245,158,11,0.5)]" />
                  <div>
                    <div className="font-bold text-amber-900 dark:text-amber-200">{tableSummaryCoverageGap} 张表缺少摘要</div>
                    <div className="mt-1 text-xs text-amber-700/70 dark:text-amber-500/70 leading-relaxed">已存在结构事实，但尚未生成 Schema Summary 知识。</div>
                  </div>
                </div>
              )}
              {activeTables.filter(t => !t.table_comment).length > 0 && (
                <div className="flex items-start gap-4">
                  <div className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.5)]" />
                  <div>
                    <div className="font-bold text-rose-900 dark:text-rose-200">部分表缺少关键注释</div>
                    <div className="mt-1 text-xs text-rose-700/70 dark:text-rose-500/70 leading-relaxed">这会严重影响大模型对业务含义的理解。</div>
                  </div>
                </div>
              )}
            </div>
            <Button
              className="w-full h-12 rounded-xl bg-amber-500 text-white hover:bg-amber-600 shadow-lg shadow-amber-500/20 font-black text-xs uppercase"
              onClick={() => router.push(`/knowledge-bases/${kbId}/review`)}
            >
              立即前往治理
            </Button>
          </section>

          <section className="rounded-[2.5rem] border bg-card p-8 shadow-sm space-y-6">
            <h2 className="flex items-center gap-2 text-sm font-black uppercase tracking-widest text-muted-foreground">
              <ShieldCheck className="h-4 w-4" /> 知识库元信息
            </h2>
            <div className="space-y-4 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground font-bold uppercase tracking-tighter">关联数据源</span>
                <span className="font-black text-foreground">{kb.datasource_name || "Internal"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground font-bold uppercase tracking-tighter">数据库类型</span>
                <Badge variant="secondary" className="px-2 py-0 text-[10px] font-black">{kb.db_type}</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground font-bold uppercase tracking-tighter">Dialect</span>
                <span className="font-mono font-bold text-foreground">{kb.dialect}</span>
              </div>
              <div className="pt-4 border-t border-dashed flex items-center justify-between">
                <span className="text-muted-foreground font-bold uppercase tracking-tighter">创建时间</span>
                <span className="font-bold text-foreground opacity-60">{formatDate(kb.created_at)}</span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
