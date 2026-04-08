"use client"

import React, { useEffect, useMemo, useState } from "react"
import { useParams } from "next/navigation"
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  MessageSquare,
  Play,
  Search,
  Sparkles,
  XCircle,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { cn, formatDate } from "@/lib/utils"

import {
  askVannaSql,
  getVannaKnowledgeBase,
  listAskRuns,
} from "../shared/vanna-api"
import { SqlAssetPromoteDialog } from "./sql-asset-promote-dialog"
import type {
  VannaAskRunRecord,
  VannaKnowledgeBaseRecord,
} from "../shared/vanna-types"

const FALLBACK_TOP_K_SQL = 8
const FALLBACK_TOP_K_SCHEMA = 12
const FALLBACK_TOP_K_DOC = 6

function getAskStatusIcon(status: string) {
  if (status === "executed") {
    return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
  }
  if (status === "failed") {
    return <XCircle className="h-3.5 w-3.5 text-rose-500" />
  }
  return <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
}

export function KnowledgeBaseRunsView() {
  const params = useParams()
  const kbId = Number(params.id)

  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState("")
  const [askRuns, setAskRuns] = useState<VannaAskRunRecord[]>([])
  const [kb, setKb] = useState<VannaKnowledgeBaseRecord | null>(null)
  const [askQuestion, setAskQuestion] = useState("")
  const [submittingAsk, setSubmittingAsk] = useState(false)
  const [promotingAskRun, setPromotingAskRun] =
    useState<VannaAskRunRecord | null>(null)

  async function loadData(showLoading = true) {
    if (!Number.isFinite(kbId)) {
      return
    }

    if (showLoading) {
      setLoading(true)
    }

    try {
      const [kbRow, askRows] = await Promise.all([
        getVannaKnowledgeBase(kbId),
        listAskRuns({ kb_id: kbId }),
      ])
      setKb(kbRow)
      setAskRuns(askRows)
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "加载 Ask 记录失败")
    } finally {
      if (showLoading) {
        setLoading(false)
      }
    }
  }

  useEffect(() => {
    if (!Number.isFinite(kbId)) {
      return
    }
    void loadData()
  }, [kbId])

  const filteredAskRuns = useMemo(() => {
    const keyword = searchTerm.trim().toLowerCase()
    return [...askRuns]
      .filter(run => {
        if (!keyword) {
          return true
        }
        const haystack = [
          String(run.id),
          run.question_text,
          run.generated_sql,
          run.execution_status,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
        return haystack.includes(keyword)
      })
      .sort(
        (left, right) =>
          new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
      )
  }, [askRuns, searchTerm])

  const askSuccessCount = askRuns.filter(
    run => run.execution_status === "executed"
  ).length
  const effectiveTopKSql = kb?.default_top_k_sql ?? FALLBACK_TOP_K_SQL
  const effectiveTopKSchema = kb?.default_top_k_schema ?? FALLBACK_TOP_K_SCHEMA
  const effectiveTopKDoc = kb?.default_top_k_doc ?? FALLBACK_TOP_K_DOC
  const topKSourceLabel =
    kb?.default_top_k_sql == null &&
    kb?.default_top_k_schema == null &&
    kb?.default_top_k_doc == null
      ? "当前未单独配置，使用系统回退值"
      : "当前优先使用知识库配置，未配置项回退到系统默认"

  async function handleAskSubmit() {
    const question = askQuestion.trim()
    if (!kb) {
      toast.error("知识库信息尚未加载完成")
      return
    }
    if (!question) {
      toast.error("请输入要测试的自然语言问题")
      return
    }

    try {
      setSubmittingAsk(true)
      const result = await askVannaSql({
        datasource_id: kb.datasource_id,
        kb_id: kb.id,
        question,
        auto_run: false,
        auto_train_on_success: false,
      })
      toast.success(`Ask 已创建，Run #${result.ask_run_id}`)
      setAskQuestion("")
      await loadData(false)
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "发起 Ask 失败")
    } finally {
      setSubmittingAsk(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-112px)] w-full items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100vh-112px)] w-full flex-col overflow-hidden">
      <div className="z-10 flex shrink-0 items-center justify-between border-b bg-background px-8 py-3 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary/10">
            <MessageSquare className="h-4 w-4 text-primary" />
          </div>
          <div>
            <div className="text-sm font-black tracking-tight">Ask 记录</div>
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
              只展示自然语言提问生成的 SQL 记录
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant="outline" className="hidden sm:inline-flex">
            Ask 成功 {askSuccessCount}/{askRuns.length}
          </Badge>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground opacity-50" />
            <Input
              value={searchTerm}
              onChange={event => setSearchTerm(event.target.value)}
              placeholder="按 Ask ID、问题或 SQL 搜索..."
              className="h-8 w-56 rounded-lg bg-zinc-50/50 pl-9 text-xs"
            />
          </div>
        </div>
      </div>

      <main className="flex-1 overflow-auto p-10">
        <div className="mx-auto max-w-7xl space-y-8">
          <section className="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
            <div className="rounded-[2rem] border bg-card p-6 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h2 className="text-sm font-black uppercase tracking-widest text-muted-foreground">
                    当前生效召回参数
                  </h2>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {topKSourceLabel}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Badge
                    variant="outline"
                    className="h-8 rounded-full px-4 text-xs font-bold"
                  >
                    SQL {effectiveTopKSql}
                  </Badge>
                  <Badge
                    variant="outline"
                    className="h-8 rounded-full px-4 text-xs font-bold"
                  >
                    表结构 {effectiveTopKSchema}
                  </Badge>
                  <Badge
                    variant="outline"
                    className="h-8 rounded-full px-4 text-xs font-bold"
                  >
                    文档 {effectiveTopKDoc}
                  </Badge>
                </div>
              </div>
            </div>

            <div className="rounded-[2rem] border bg-card p-6 shadow-sm">
              <div className="space-y-4">
                <div>
                  <h2 className="text-sm font-black uppercase tracking-widest text-muted-foreground">
                    发起 Ask
                  </h2>
                  <p className="mt-2 text-xs text-muted-foreground">
                    当前入口只做 SQL 生成与召回验证，不直接执行数据库查询。
                  </p>
                </div>
                <Textarea
                  value={askQuestion}
                  onChange={event => setAskQuestion(event.target.value)}
                  placeholder="例如：查询所有管理员用户"
                  className="min-h-24 resize-none"
                />
                <div className="flex items-center justify-end">
                  <Button
                    onClick={() => void handleAskSubmit()}
                    disabled={submittingAsk || !kb}
                  >
                    {submittingAsk ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="mr-2 h-4 w-4" />
                    )}
                    发起 Ask
                  </Button>
                </div>
              </div>
            </div>
          </section>

          <section className="rounded-[2rem] border bg-card p-6 shadow-sm">
            <div className="flex items-start gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-zinc-900 text-zinc-100">
                <Sparkles className="h-5 w-5" />
              </div>
              <div className="space-y-2">
                <h2 className="text-sm font-black uppercase tracking-widest text-muted-foreground">
                  Ask 输出如何被复用
                </h2>
                <p className="max-w-4xl text-sm leading-6 text-muted-foreground">
                  Ask 页面只负责沉淀自然语言提问到 SQL 的生成记录。确认某条 Ask
                  结果稳定后，可以继续把它提升为 SQL 资产，或者回到 Train 方法页把它整理成正式训练样本。
                </p>
              </div>
            </div>
          </section>

          <div className="overflow-hidden rounded-[2rem] border bg-card shadow-sm">
            <Table>
              <TableHeader className="bg-muted/30">
                <TableRow className="border-none hover:bg-transparent">
                  <TableHead className="w-16 text-[10px] font-black uppercase">
                    Ask ID
                  </TableHead>
                  <TableHead className="min-w-[300px] text-[10px] font-black uppercase">
                    用户问题
                  </TableHead>
                  <TableHead className="text-center text-[10px] font-black uppercase">
                    状态
                  </TableHead>
                  <TableHead className="text-[10px] font-black uppercase">
                    SQL 置信度
                  </TableHead>
                  <TableHead className="text-right text-[10px] font-black uppercase">
                    操作
                  </TableHead>
                  <TableHead className="text-[10px] font-black uppercase">
                    创建时间
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredAskRuns.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className="py-12 text-center text-sm text-muted-foreground"
                    >
                      当前没有 Ask 记录。
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredAskRuns.map(run => (
                    <TableRow
                      key={run.id}
                      className="border-border/40 hover:bg-muted/20"
                    >
                      <TableCell className="font-mono text-[10px] text-muted-foreground">
                        #{run.id}
                      </TableCell>
                      <TableCell>
                        <div className="max-w-[520px]">
                          <div className="truncate text-xs font-bold">
                            {run.question_text}
                          </div>
                          {run.generated_sql ? (
                            <div className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
                              {run.generated_sql}
                            </div>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center justify-center gap-1.5">
                          {getAskStatusIcon(run.execution_status)}
                          <span className="text-[9px] font-black uppercase">
                            {run.execution_status}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        {typeof run.sql_confidence === "number" ? (
                          <div className="flex items-center gap-2">
                            <div className="h-1 w-12 overflow-hidden rounded-full bg-muted">
                              <div
                                className={cn(
                                  "h-full",
                                  run.sql_confidence > 0.9
                                    ? "bg-emerald-500"
                                    : "bg-amber-500"
                                )}
                                style={{
                                  width: `${Math.max(
                                    0,
                                    Math.min(1, run.sql_confidence)
                                  ) * 100}%`,
                                }}
                              />
                            </div>
                            <span className="font-mono text-[10px] font-black">
                              {(run.sql_confidence * 100).toFixed(0)}%
                            </span>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            暂无
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 rounded-full px-3 text-[10px] font-bold"
                          onClick={() => setPromotingAskRun(run)}
                          disabled={!run.generated_sql}
                        >
                          提升为 SQL 资产
                        </Button>
                      </TableCell>
                      <TableCell className="text-[10px] font-bold uppercase text-muted-foreground">
                        {formatDate(run.created_at)}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </div>
      </main>

      <SqlAssetPromoteDialog
        open={Boolean(promotingAskRun)}
        onOpenChange={open => {
          if (!open) {
            setPromotingAskRun(null)
          }
        }}
        source={promotingAskRun ? { kind: "ask_run", row: promotingAskRun } : null}
      />
    </div>
  )
}
