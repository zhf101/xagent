"use client"

import React, { useEffect, useMemo, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import {
  BookOpen,
  Braces,
  ChevronRight,
  Copy,
  Database,
  Loader2,
  MessageSquare,
  Sparkles,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

import { getVannaKnowledgeBase } from "./vanna-api"
import type { VannaKnowledgeBaseRecord } from "./vanna-types"

interface MethodCard {
  title: string
  description: string
  fields: string[]
  actionLabel: string
  actionHref: string
  icon: React.ElementType
}

interface SnippetCard {
  id: string
  title: string
  description: string
  methodName: string
  backendPath: string
  snippet: string
}

export function KnowledgeBaseTrainMethodView() {
  const params = useParams()
  const router = useRouter()
  const kbId = Number(params.id)

  const [loading, setLoading] = useState(true)
  const [kb, setKb] = useState<VannaKnowledgeBaseRecord | null>(null)

  useEffect(() => {
    if (!Number.isFinite(kbId)) {
      return
    }

    let cancelled = false

    async function loadKb() {
      setLoading(true)
      try {
        const row = await getVannaKnowledgeBase(kbId)
        if (!cancelled) {
          setKb(row)
        }
      } catch (error) {
        console.error(error)
        if (!cancelled) {
          toast.error(error instanceof Error ? error.message : "加载 Train 方法失败")
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadKb()

    return () => {
      cancelled = true
    }
  }, [kbId])

  const methodCards = useMemo<MethodCard[]>(() => {
    return [
      {
        title: "SQL 问答训练",
        description:
          "把真实业务问题和标准 SQL 写进知识库，后续 Ask 会优先召回这类高质量样本。",
        fields: ["question", "sql", "publish"],
        actionLabel: "去新建 SQL 问答对",
        actionHref: `/knowledge-bases/${kbId}/training/question-sql/new`,
        icon: MessageSquare,
      },
      {
        title: "文档知识训练",
        description:
          "把口径、业务规则和术语说明写入知识库，补足表结构本身表达不了的业务语义。",
        fields: ["title", "documentation", "publish"],
        actionLabel: "去填写文档知识",
        actionHref: `/knowledge-bases/${kbId}/training/documentation/new`,
        icon: BookOpen,
      },
      {
        title: "结构摘要训练",
        description:
          "先采集 schema，再通过 bootstrap 生成候选结构摘要，让知识库先具备表级背景信息。",
        fields: ["bootstrap_schema", "datasource_id"],
        actionLabel: "去重新采集元数据",
        actionHref: `/knowledge-bases/${kbId}/harvest`,
        icon: Database,
      },
    ]
  }, [kbId])

  const snippetCards = useMemo<SnippetCard[]>(() => {
    const datasourceId = kb?.datasource_id ?? 0
    return [
      {
        id: "question-sql",
        title: "训练 SQL 问答对",
        description: "对应后端 `TrainService.train_question_sql`。",
        methodName: "vanna.train(question=..., sql=...)",
        backendPath: "POST /api/vanna/train",
        snippet: `{
  "datasource_id": ${datasourceId},
  "question": "查询昨日订单",
  "sql": "SELECT * FROM orders WHERE biz_date = CURRENT_DATE - 1",
  "publish": true
}`,
      },
      {
        id: "documentation",
        title: "训练文档知识",
        description: "对应后端 `TrainService.train_documentation`。",
        methodName: "vanna.train(documentation=..., title=...)",
        backendPath: "POST /api/vanna/train",
        snippet: `{
  "datasource_id": ${datasourceId},
  "title": "订单状态口径说明",
  "documentation": "已支付订单才计入成交订单，取消单不纳入统计。",
  "publish": true
}`,
      },
      {
        id: "bootstrap-schema",
        title: "生成结构摘要候选",
        description: "对应后端 `TrainService.bootstrap_schema`。",
        methodName: "vanna.train(bootstrap_schema=True)",
        backendPath: "POST /api/vanna/train",
        snippet: `{
  "datasource_id": ${datasourceId},
  "bootstrap_schema": true
}`,
      },
    ]
  }, [kb])

  async function handleCopy(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      toast.success("训练示例已复制")
    } catch (error) {
      console.error(error)
      toast.error("复制失败，请手动复制")
    }
  }

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-112px)] w-full items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  if (!kb) {
    return null
  }

  return (
    <div className="flex h-[calc(100vh-112px)] w-full flex-col overflow-hidden">
      <main className="flex-1 overflow-auto p-10">
        <div className="mx-auto max-w-7xl space-y-8">
          <section className="overflow-hidden rounded-[2rem] border bg-card shadow-sm">
            <div className="grid gap-0 lg:grid-cols-[1.3fr_0.9fr]">
              <div className="space-y-5 p-8">
                <Badge className="w-fit border-none bg-primary/10 px-3 py-1 text-[10px] font-black uppercase text-primary">
                  vanna.train
                </Badge>
                <div className="space-y-3">
                  <h1 className="text-3xl font-black tracking-tight">
                    用训练条目把 SQL 知识库喂给 Ask
                  </h1>
                  <p className="max-w-3xl text-sm leading-7 text-muted-foreground">
                    这个页面把前端训练入口和后端训练方式放到一起。你可以直接查看
                    `vanna.train` 在系统里的落点，以及当前知识库应该传哪些字段。
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-xs font-bold">
                  <Badge variant="outline" className="rounded-full px-4 py-1.5">
                    数据源 #{kb.datasource_id}
                  </Badge>
                  <Badge variant="outline" className="rounded-full px-4 py-1.5">
                    {kb.system_short}/{kb.env}
                  </Badge>
                  <Badge variant="outline" className="rounded-full px-4 py-1.5">
                    {kb.kb_code}
                  </Badge>
                </div>
              </div>

              <div className="border-l bg-zinc-50/70 p-8 dark:bg-zinc-900/40">
                <div className="space-y-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-zinc-900 text-zinc-100">
                      <Sparkles className="h-5 w-5" />
                    </div>
                    <div>
                      <div className="text-sm font-black">后端训练落点</div>
                      <div className="text-[11px] font-mono text-muted-foreground">
                        src/xagent/web/api/vanna_sql.py
                      </div>
                    </div>
                  </div>
                  <div className="space-y-3 text-sm leading-6 text-muted-foreground">
                    <p>1. 前端训练表单最终统一请求 `POST /api/vanna/train`。</p>
                    <p>2. 后端根据字段组合分流到 question_sql、documentation 或 bootstrap_schema。</p>
                    <p>3. 写入训练条目后会触发 `IndexService.reindex_entry`，让 Ask 能参与召回。</p>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="grid gap-6 xl:grid-cols-3">
            {methodCards.map(card => {
              const Icon = card.icon
              return (
                <div
                  key={card.title}
                  className="rounded-[2rem] border bg-card p-6 shadow-sm"
                >
                  <div className="flex h-full flex-col gap-5">
                    <div className="flex items-start gap-4">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-primary/10">
                        <Icon className="h-5 w-5 text-primary" />
                      </div>
                      <div className="space-y-2">
                        <h2 className="text-lg font-black tracking-tight">
                          {card.title}
                        </h2>
                        <p className="text-sm leading-6 text-muted-foreground">
                          {card.description}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      {card.fields.map(field => (
                        <Badge key={field} variant="outline" className="font-mono">
                          {field}
                        </Badge>
                      ))}
                    </div>

                    <div className="mt-auto">
                      <Button
                        variant="outline"
                        className="w-full justify-between rounded-full px-5 font-bold"
                        onClick={() => router.push(card.actionHref)}
                      >
                        {card.actionLabel}
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              )
            })}
          </section>

          <section className="grid gap-6">
            {snippetCards.map(card => (
              <div
                key={card.id}
                className="overflow-hidden rounded-[2rem] border bg-card shadow-sm"
              >
                <div className="flex flex-wrap items-start justify-between gap-4 border-b bg-zinc-50/70 px-6 py-5 dark:bg-zinc-900/40">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge className="border-none bg-primary/10 text-primary">
                        {card.methodName}
                      </Badge>
                      <Badge variant="outline">{card.backendPath}</Badge>
                    </div>
                    <div>
                      <h3 className="text-base font-black tracking-tight">
                        {card.title}
                      </h3>
                      <p className="text-sm text-muted-foreground">
                        {card.description}
                      </p>
                    </div>
                  </div>

                  <Button
                    variant="outline"
                    className="rounded-full px-4 text-xs font-bold"
                    onClick={() => void handleCopy(card.snippet)}
                  >
                    <Copy className="mr-2 h-3.5 w-3.5" />
                    复制请求体
                  </Button>
                </div>

                <div className="grid gap-0 border-t lg:grid-cols-[0.9fr_1.1fr] lg:border-t-0">
                  <div className="space-y-4 border-r p-6">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-zinc-900 text-zinc-100">
                        <Braces className="h-4 w-4" />
                      </div>
                      <div>
                        <div className="text-sm font-black">字段说明</div>
                        <div className="text-xs text-muted-foreground">
                          复制右侧请求体即可直接对照后端接口调用。
                        </div>
                      </div>
                    </div>
                    <ul className="space-y-3 text-sm leading-6 text-muted-foreground">
                      <li>`datasource_id` 决定写入哪个默认知识库。</li>
                      <li>`publish=true` 直接发布，`false` 会保存为候选。</li>
                      <li>`question + sql` 和 `title + documentation` 是两条不同训练路径。</li>
                      <li>`bootstrap_schema=true` 会基于已采集 schema 生成候选结构摘要。</li>
                    </ul>
                  </div>

                  <div className="bg-zinc-950 p-6 text-zinc-100">
                    <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-sm leading-6">
                      {card.snippet}
                    </pre>
                  </div>
                </div>
              </div>
            ))}
          </section>
        </div>
      </main>
    </div>
  )
}
