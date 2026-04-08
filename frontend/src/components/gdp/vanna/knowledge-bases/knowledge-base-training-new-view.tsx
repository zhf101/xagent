"use client"

import React, { useEffect, useMemo, useState } from "react"
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
import { useI18n } from "@/contexts/i18n-context"

import {
  getTrainingEntry,
  getVannaKnowledgeBase,
  trainVannaEntry,
  updateTrainingEntry,
} from "../shared/vanna-api"
import type { VannaKnowledgeBaseRecord } from "../shared/vanna-types"

export type NewTrainingType = "question_sql" | "documentation"

interface KnowledgeBaseTrainingNewViewProps {
  type: NewTrainingType
  entryId?: number
}

function getTypeCopy(
  type: NewTrainingType,
  t: (key: string, vars?: Record<string, string | number>) => string
) {
  if (type === "question_sql") {
    return {
      Icon: MessageSquare,
      typeLabel: t("kb.training.types.question_sql"),
      title: t("kb.trainingNew.questionSql.title"),
      description: t("kb.trainingNew.questionSql.description"),
      detailTitle: t("kb.trainingNew.questionSql.detailTitle"),
      scopeSuffix: t("kb.trainingNew.scope.questionSqlSuffix"),
    }
  }

  return {
    Icon: BookOpen,
    typeLabel: t("kb.training.types.documentation"),
    title: t("kb.trainingNew.documentation.title"),
    description: t("kb.trainingNew.documentation.description"),
    detailTitle: t("kb.trainingNew.documentation.detailTitle"),
    scopeSuffix: t("kb.trainingNew.scope.documentationSuffix"),
  }
}

function getListHref(kbId: number, type: NewTrainingType) {
  return type === "question_sql"
    ? `/gdp/vanna/knowledge-bases/${kbId}/training/question-sql`
    : `/gdp/vanna/knowledge-bases/${kbId}/training/documentation`
}

export function KnowledgeBaseTrainingNewView({
  type,
  entryId,
}: KnowledgeBaseTrainingNewViewProps) {
  const { t } = useI18n()
  const params = useParams()
  const router = useRouter()
  const kbId = Number(params.id)

  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [kb, setKb] = useState<VannaKnowledgeBaseRecord | null>(null)
  const [entryLoading, setEntryLoading] = useState(false)
  const [question, setQuestion] = useState("")
  const [sql, setSql] = useState("")
  const [title, setTitle] = useState("")
  const [documentation, setDocumentation] = useState("")

  const copy = useMemo(() => getTypeCopy(type, t), [type, t])

  useEffect(() => {
    async function loadKb() {
      setLoading(true)
      try {
        setKb(await getVannaKnowledgeBase(kbId))
      } catch (error) {
        console.error(error)
        toast.error(
          error instanceof Error
            ? error.message
            : t("kb.trainingNew.feedback.loadFailed")
        )
      } finally {
        setLoading(false)
      }
    }

    if (Number.isFinite(kbId)) {
      void loadKb()
    }
  }, [kbId, t])

  useEffect(() => {
    if (!entryId || type !== "question_sql") {
      return
    }

    const targetEntryId = entryId
    let cancelled = false

    async function loadEntry() {
      setEntryLoading(true)
      try {
        const entry = await getTrainingEntry(targetEntryId)
        if (cancelled) {
          return
        }
        setQuestion(entry.question_text || "")
        setSql(entry.sql_text || "")
      } catch (error) {
        console.error(error)
        if (!cancelled) {
          toast.error(error instanceof Error ? error.message : "加载 SQL 问答对失败")
        }
      } finally {
        if (!cancelled) {
          setEntryLoading(false)
        }
      }
    }

    void loadEntry()

    return () => {
      cancelled = true
    }
  }, [entryId, type])

  async function handleSubmit(publish: boolean) {
    if (!kb) {
      return
    }

    setSubmitting(true)
    try {
      if (type === "question_sql" && entryId) {
        const targetEntryId = entryId
        if (!question.trim() || !sql.trim()) {
          toast.error(t("kb.trainingNew.feedback.questionSqlRequired"))
          return
        }
        await updateTrainingEntry(targetEntryId, {
          question: question.trim(),
          sql: sql.trim(),
        })
      } else if (type === "question_sql") {
        if (!question.trim() || !sql.trim()) {
          toast.error(t("kb.trainingNew.feedback.questionSqlRequired"))
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
          toast.error(t("kb.trainingNew.feedback.documentationRequired"))
          return
        }
        await trainVannaEntry({
          datasource_id: kb.datasource_id,
          title: title.trim(),
          documentation: documentation.trim(),
          publish,
        })
      }

      toast.success(
        entryId
          ? "SQL 问答对已更新"
          : publish
          ? t("kb.trainingNew.feedback.publishSuccess")
          : t("kb.trainingNew.feedback.saveCandidateSuccess")
      )
      router.push(
        entryId
          ? getListHref(kb.id, type)
          : publish
          ? getListHref(kb.id, type)
          : getListHref(kb.id, type)
      )
    } catch (error) {
      console.error(error)
      toast.error(
        error instanceof Error
          ? error.message
          : t("kb.trainingNew.feedback.saveFailed")
      )
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

  const Icon = copy.Icon

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-zinc-50/50 text-foreground">
      <header className="z-10 flex h-16 shrink-0 items-center justify-between border-b bg-background px-8 shadow-sm">
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="icon"
            className="h-9 w-9 rounded-full"
            onClick={() => router.push(getListHref(kb.id, type))}
          >
            <ChevronLeft className="h-5 w-5" />
          </Button>
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10">
              <Icon className="h-4 w-4 text-primary" />
            </div>
            <div className="flex flex-col">
              <h1 className="text-base font-bold tracking-tight">
                {entryId && type === "question_sql" ? "修改 SQL 问答对" : copy.title}
              </h1>
              <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                {kb.kb_code}
              </div>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {entryId ? null : (
            <Button
              variant="outline"
              className="h-10 rounded-full px-6 font-bold"
              onClick={() => void handleSubmit(false)}
              disabled={submitting}
            >
              {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {t("kb.trainingNew.actions.saveCandidate")}
            </Button>
          )}
          <Button
            className="h-10 rounded-full bg-primary px-8 font-bold shadow-lg shadow-primary/20"
            onClick={() => void handleSubmit(true)}
            disabled={submitting || entryLoading}
          >
            {submitting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            {entryId ? "保存修改" : t("kb.trainingNew.actions.publish")}
          </Button>
        </div>
      </header>

      <main className="flex flex-1 justify-center overflow-y-auto bg-white p-8 dark:bg-zinc-950">
        <div className="w-full max-w-4xl space-y-10">
          <section className="rounded-[2rem] border bg-zinc-50/70 p-6 shadow-sm">
            <div className="flex items-start gap-4">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-[1.25rem] bg-primary text-primary-foreground shadow-lg shadow-primary/15">
                <Icon className="h-6 w-6" />
              </div>
              <div className="space-y-2">
                <Badge variant="outline">{copy.typeLabel}</Badge>
                <div className="text-xl font-black">{copy.title}</div>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {copy.description}
                </p>
              </div>
            </div>
          </section>

          <section className="space-y-8 pb-20">
            <div className="flex items-center gap-2 border-b-2 pb-2">
              <Sparkles className="h-5 w-5 text-primary" />
              <h2 className="text-xl font-black">{copy.detailTitle}</h2>
              <Badge variant="outline">
                {kb.system_short}/{kb.env}
              </Badge>
            </div>

            <div className="grid grid-cols-2 gap-8">
              {type === "question_sql" ? (
                <>
                  <div className="col-span-2 space-y-3">
                    <Label className="text-xs font-black uppercase tracking-wider">
                      {t("kb.trainingNew.form.question")} *
                    </Label>
                    <Input
                      value={question}
                      onChange={event => setQuestion(event.target.value)}
                      className="h-12 rounded-2xl text-lg font-bold"
                      placeholder={t("kb.trainingNew.placeholders.question")}
                      disabled={entryLoading}
                    />
                  </div>
                  <div className="col-span-2 space-y-3">
                    <div className="flex items-center justify-between">
                      <Label className="text-xs font-black uppercase tracking-wider">
                        {t("kb.trainingNew.form.standardSql")} *
                      </Label>
                      <Badge
                        variant="outline"
                        className="bg-muted text-[10px] text-muted-foreground"
                      >
                        SQL
                      </Badge>
                    </div>
                    <Textarea
                      value={sql}
                      onChange={event => setSql(event.target.value)}
                      className="min-h-[220px] rounded-3xl border border-border bg-background p-6 font-mono text-sm text-foreground shadow-sm focus-visible:ring-primary"
                      placeholder={t("kb.trainingNew.placeholders.sql")}
                      disabled={entryLoading}
                    />
                  </div>
                </>
              ) : (
                <>
                  <div className="col-span-2 space-y-3">
                    <Label className="text-xs font-black uppercase tracking-wider">
                      {t("kb.trainingNew.form.documentTitle")} *
                    </Label>
                    <Input
                      value={title}
                      onChange={event => setTitle(event.target.value)}
                      className="h-12 rounded-2xl text-lg font-bold"
                      placeholder={t("kb.trainingNew.placeholders.documentTitle")}
                    />
                  </div>
                  <div className="col-span-2 space-y-3">
                    <Label className="text-xs font-black uppercase tracking-wider">
                      {t("kb.trainingNew.form.documentBody")} *
                    </Label>
                    <Textarea
                      value={documentation}
                      onChange={event => setDocumentation(event.target.value)}
                      className="min-h-[320px] rounded-3xl border-none bg-zinc-50 p-6 leading-relaxed shadow-inner focus-visible:ring-primary"
                      placeholder={t("kb.trainingNew.placeholders.documentation")}
                    />
                  </div>
                </>
              )}

              <div className="col-span-2 rounded-3xl border-2 border-dashed border-zinc-100 p-6">
                <div className="text-sm font-bold">
                  {t("kb.trainingNew.scope.title")}
                </div>
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  {t("kb.trainingNew.scope.descriptionPrefix")}{" "}
                  <span className="font-mono">{kb.system_short}</span>
                  {" / "}
                  <span className="font-mono">{kb.env}</span>
                  {" "}
                  {copy.scopeSuffix}
                </p>
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}
