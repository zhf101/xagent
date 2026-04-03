"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import {
  BookOpen,
  ChevronLeft,
  Loader2,
  MessageSquare,
  Save,
  Sparkles,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

import { getVannaKnowledgeBase, trainVannaEntry } from "./vanna-api"
import type { VannaKnowledgeBaseRecord } from "./vanna-types"

type NewTrainingType = "question_sql" | "documentation"

export function KnowledgeBaseTrainingNewView() {
  const params = useParams()
  const router = useRouter()
  const kbId = Number(params.id)

  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [kb, setKb] = useState<VannaKnowledgeBaseRecord | null>(null)
  const [type, setType] = useState<NewTrainingType>("question_sql")
  const [question, setQuestion] = useState("")
  const [sql, setSql] = useState("")
  const [title, setTitle] = useState("")
  const [documentation, setDocumentation] = useState("")

  useEffect(() => {
    async function loadKb() {
      setLoading(true)
      try {
        setKb(await getVannaKnowledgeBase(kbId))
      } catch (error) {
        console.error(error)
        toast.error(error instanceof Error ? error.message : "知识库加载失败")
      } finally {
        setLoading(false)
      }
    }

    if (Number.isFinite(kbId)) {
      void loadKb()
    }
  }, [kbId])

  async function handleSubmit(publish: boolean) {
    if (!kb) {
      return
    }
    setSubmitting(true)
    try {
      if (type === "question_sql") {
        if (!question.trim() || !sql.trim()) {
          toast.error("请填写用户问题和标准 SQL")
          return
        }
        await trainVannaEntry({
          datasource_id: kb.datasource_id,
          question: question.trim(),
          sql: sql.trim(),
          publish,
        })
      } else {
        if (!title.trim() || !documentation.trim()) {
          toast.error("请填写文档标题和正文")
          return
        }
        await trainVannaEntry({
          datasource_id: kb.datasource_id,
          title: title.trim(),
          documentation: documentation.trim(),
          publish,
        })
      }
      toast.success(publish ? "训练知识已发布" : "训练知识已保存为候选")
      router.push(`/knowledge-bases/${kb.id}/training`)
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "保存训练知识失败")
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  if (!kb) {
    return null
  }

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-zinc-50/50 text-foreground">
      <header className="z-10 flex h-16 shrink-0 items-center justify-between border-b bg-background px-8 shadow-sm">
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="icon"
            className="h-9 w-9 rounded-full"
            onClick={() => router.push(`/knowledge-bases/${kb.id}/training`)}
          >
            <ChevronLeft className="h-5 w-5" />
          </Button>
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10">
              {type === "question_sql" ? (
                <MessageSquare className="h-4 w-4 text-primary" />
              ) : (
                <BookOpen className="h-4 w-4 text-primary" />
              )}
            </div>
            <div className="flex flex-col">
              <h1 className="text-base font-bold tracking-tight">录入训练知识</h1>
              <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                {kb.kb_code}
              </div>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            className="h-10 rounded-full px-6 font-bold"
            onClick={() => void handleSubmit(false)}
            disabled={submitting}
          >
            {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            保存为 Candidate
          </Button>
          <Button
            className="h-10 rounded-full bg-primary px-8 font-bold shadow-lg shadow-primary/20"
            onClick={() => void handleSubmit(true)}
            disabled={submitting}
          >
            {submitting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            直接发布
          </Button>
        </div>
      </header>

      <main className="flex flex-1 justify-center overflow-y-auto bg-white p-8 dark:bg-zinc-950">
        <div className="w-full max-w-4xl space-y-10">
          <div className="space-y-4">
            <Label className="text-xs font-black uppercase tracking-widest text-muted-foreground">
              选择知识类型
            </Label>
            <div className="grid grid-cols-2 gap-4">
              <button
                type="button"
                onClick={() => setType("question_sql")}
                className={cn(
                  "flex items-start gap-4 rounded-[2rem] border-2 p-6 text-left transition-all",
                  type === "question_sql"
                    ? "border-primary bg-primary/5 shadow-xl ring-4 ring-primary/5"
                    : "border-transparent bg-zinc-50 hover:bg-zinc-100"
                )}
              >
                <div
                  className={cn(
                    "rounded-2xl p-3",
                    type === "question_sql" ? "bg-primary text-white" : "bg-muted"
                  )}
                >
                  <MessageSquare className="h-6 w-6" />
                </div>
                <div className="space-y-1">
                  <div className="text-lg font-black">Question SQL</div>
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    录入真实业务问题与标准 SQL，作为生成 SQL 的 few-shot 样例。
                  </p>
                </div>
              </button>
              <button
                type="button"
                onClick={() => setType("documentation")}
                className={cn(
                  "flex items-start gap-4 rounded-[2rem] border-2 p-6 text-left transition-all",
                  type === "documentation"
                    ? "border-primary bg-primary/5 shadow-xl ring-4 ring-primary/5"
                    : "border-transparent bg-zinc-50 hover:bg-zinc-100"
                )}
              >
                <div
                  className={cn(
                    "rounded-2xl p-3",
                    type === "documentation" ? "bg-primary text-white" : "bg-muted"
                  )}
                >
                  <BookOpen className="h-6 w-6" />
                </div>
                <div className="space-y-1">
                  <div className="text-lg font-black">Documentation</div>
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    录入业务规则、口径定义和术语解释，补足结构事实无法表达的业务语义。
                  </p>
                </div>
              </button>
            </div>
          </div>

          <div className="space-y-8 pb-20">
            <div className="flex items-center gap-2 border-b-2 pb-2">
              <Sparkles className="h-5 w-5 text-primary" />
              <h2 className="text-xl font-black">填写知识详情</h2>
              <Badge variant="outline">
                {kb.system_short}/{kb.env}
              </Badge>
            </div>

            <div className="grid grid-cols-2 gap-8">
              {type === "question_sql" ? (
                <>
                  <div className="col-span-2 space-y-3">
                    <Label className="text-xs font-black uppercase tracking-wider">
                      用户问题 *
                    </Label>
                    <Input
                      value={question}
                      onChange={event => setQuestion(event.target.value)}
                      className="h-12 rounded-2xl text-lg font-bold"
                      placeholder="例如：查询近一个月销售额最高的前 10 名客户"
                    />
                  </div>
                  <div className="col-span-2 space-y-3">
                    <div className="flex items-center justify-between">
                      <Label className="text-xs font-black uppercase tracking-wider">
                        标准 SQL *
                      </Label>
                      <Badge variant="outline" className="border-none bg-zinc-900 text-[10px] text-zinc-100">
                        SQL
                      </Badge>
                    </div>
                    <Textarea
                      value={sql}
                      onChange={event => setSql(event.target.value)}
                      className="min-h-[220px] rounded-3xl border-none bg-zinc-900 p-6 font-mono text-sm text-zinc-100 shadow-2xl focus-visible:ring-primary"
                      placeholder="SELECT ..."
                    />
                  </div>
                </>
              ) : (
                <>
                  <div className="col-span-2 space-y-3">
                    <Label className="text-xs font-black uppercase tracking-wider">
                      文档标题 *
                    </Label>
                    <Input
                      value={title}
                      onChange={event => setTitle(event.target.value)}
                      className="h-12 rounded-2xl text-lg font-bold"
                      placeholder="例如：客户分级定义与计算逻辑"
                    />
                  </div>
                  <div className="col-span-2 space-y-3">
                    <Label className="text-xs font-black uppercase tracking-wider">
                      文档正文 *
                    </Label>
                    <Textarea
                      value={documentation}
                      onChange={event => setDocumentation(event.target.value)}
                      className="min-h-[320px] rounded-3xl border-none bg-zinc-50 p-6 leading-relaxed shadow-inner focus-visible:ring-primary"
                      placeholder="请输入业务详细说明..."
                    />
                  </div>
                </>
              )}

              <div className="col-span-2 rounded-3xl border-2 border-dashed border-zinc-100 p-6">
                <div className="text-sm font-bold">写入范围说明</div>
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  当前版本会把知识写入与数据源强绑定的知识库中，并自动继承
                  {" "}
                  <span className="font-mono">{kb.system_short}</span>
                  {" / "}
                  <span className="font-mono">{kb.env}</span>
                  {" "}
                  宿主标识。Question SQL 会写入问题和 SQL，Documentation 会写入标题和文档正文。
                </p>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

