"use client"

import React, { useEffect, useMemo, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import {
  BookOpen,
  CheckCircle2,
  Clock,
  FileCode,
  Loader2,
  MessageSquare,
  Plus,
  Search,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useI18n } from "@/contexts/i18n-context"
import { cn, formatDate } from "@/lib/utils"

import { listTrainingEntries, listVannaSqlAssets } from "./vanna-api"
import { SqlAssetPromoteDialog } from "./sql-asset-promote-dialog"
import type { VannaSqlAssetRecord, VannaTrainingEntryRecord } from "./vanna-types"

type TrainingEntryType = "question_sql" | "documentation"

interface KnowledgeBaseTrainingViewProps {
  entryType: TrainingEntryType
}

function getLifecycleTone(status: string) {
  if (status === "published") {
    return "bg-emerald-500/10 text-emerald-600 border-emerald-200/50"
  }
  if (status === "candidate") {
    return "bg-amber-500/10 text-amber-600 border-amber-200/50"
  }
  return "bg-zinc-500/10 text-zinc-600 border-zinc-200/50"
}

function getEntryIcon(type: string) {
  if (type === "question_sql") return MessageSquare
  if (type === "documentation") return BookOpen
  return FileCode
}

function getEntryBody(
  entry: VannaTrainingEntryRecord,
  t: (key: string, vars?: Record<string, string | number>) => string
) {
  if (entry.entry_type === "question_sql") {
    return {
      primaryLabel: t("kb.training.detail.question"),
      primaryBody: entry.question_text || t("kb.training.detail.emptyQuestion"),
      secondaryLabel: t("kb.training.detail.standardSql"),
      secondaryBody: entry.sql_text || t("kb.training.detail.emptySql"),
      tertiaryLabel: t("kb.training.detail.explanation"),
      tertiaryBody: entry.sql_explanation || "",
      secondaryIsCode: true,
    }
  }

  return {
    primaryLabel: t("kb.training.detail.documentBody"),
    primaryBody: entry.doc_text || t("kb.training.detail.emptyDocument"),
    secondaryLabel: "",
    secondaryBody: "",
    tertiaryLabel: "",
    tertiaryBody: "",
    secondaryIsCode: false,
  }
}

export function KnowledgeBaseTrainingView({
  entryType,
}: KnowledgeBaseTrainingViewProps) {
  const { t } = useI18n()
  const params = useParams()
  const router = useRouter()
  const kbId = Number(params.id)

  const [loading, setLoading] = useState(true)
  const [entries, setEntries] = useState<VannaTrainingEntryRecord[]>([])
  const [assets, setAssets] = useState<VannaSqlAssetRecord[]>([])
  const [selectedItemId, setSelectedItemId] = useState<number | null>(null)
  const [searchTerm, setSearchTerm] = useState("")
  const [promotingEntry, setPromotingEntry] =
    useState<VannaTrainingEntryRecord | null>(null)

  async function loadData(showLoading = true) {
    if (!Number.isFinite(kbId)) {
      return
    }

    if (showLoading) {
      setLoading(true)
    }

    try {
      const [rows, assetRows] = await Promise.all([
        listTrainingEntries({ kb_id: kbId, entry_type: entryType }),
        entryType === "question_sql"
          ? listVannaSqlAssets({ kb_id: kbId })
          : Promise.resolve([] as VannaSqlAssetRecord[]),
      ])
      setEntries(rows)
      setAssets(assetRows)
    } catch (error) {
      console.error(error)
      toast.error(
        error instanceof Error ? error.message : t("kb.training.feedback.loadFailed")
      )
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

    let cancelled = false

    async function loadInitialData() {
      setLoading(true)
      try {
        const [rows, assetRows] = await Promise.all([
          listTrainingEntries({ kb_id: kbId, entry_type: entryType }),
          entryType === "question_sql"
            ? listVannaSqlAssets({ kb_id: kbId })
            : Promise.resolve([] as VannaSqlAssetRecord[]),
        ])
        if (!cancelled) {
          setEntries(rows)
          setAssets(assetRows)
        }
      } catch (error) {
        console.error(error)
        if (!cancelled) {
          toast.error(
            error instanceof Error
              ? error.message
              : t("kb.training.feedback.loadFailed")
          )
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadInitialData()

    return () => {
      cancelled = true
    }
  }, [entryType, kbId, t])

  useEffect(() => {
    setSelectedItemId(null)
    setSearchTerm("")
  }, [entryType, kbId])

  const filteredEntries = useMemo(() => {
    const keyword = searchTerm.trim().toLowerCase()
    return [...entries]
      .filter(entry => {
        if (!keyword) {
          return true
        }
        const haystack = [
          entry.title,
          entry.entry_code,
          entry.question_text,
          entry.doc_text,
          entry.sql_text,
          entry.schema_name,
          entry.table_name,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
        return haystack.includes(keyword)
      })
      .sort((left, right) => {
        return new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime()
      })
  }, [entries, searchTerm])

  useEffect(() => {
    if (filteredEntries.length === 0) {
      setSelectedItemId(null)
      return
    }
    if (
      selectedItemId === null ||
      !filteredEntries.some(item => item.id === selectedItemId)
    ) {
      setSelectedItemId(filteredEntries[0].id)
    }
  }, [filteredEntries, selectedItemId])

  const selectedItem =
    filteredEntries.find(item => item.id === selectedItemId) ||
    entries.find(item => item.id === selectedItemId) ||
    null
  const promotedAssetsByEntryId = useMemo(() => {
    return assets.reduce<Record<number, VannaSqlAssetRecord[]>>((acc, asset) => {
      if (!asset.origin_training_entry_id) {
        return acc
      }
      const key = asset.origin_training_entry_id
      acc[key] = [...(acc[key] || []), asset]
      return acc
    }, {})
  }, [assets])

  const detail = selectedItem ? getEntryBody(selectedItem, t) : null
  const typeLabel = t(`kb.training.types.${entryType}`)
  const TypeIcon = getEntryIcon(entryType)
  const selectedPromotedAssets = selectedItem
    ? promotedAssetsByEntryId[selectedItem.id] || []
    : []

  function handleCreateKnowledge() {
    if (entryType === "question_sql") {
      router.push(`/knowledge-bases/${kbId}/training/question-sql/new`)
      return
    }
    router.push(`/knowledge-bases/${kbId}/training/documentation/new`)
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
      <div className="z-10 flex shrink-0 items-center justify-between border-b bg-background px-8 py-4 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary/10">
            <TypeIcon className="h-4 w-4 text-primary" />
          </div>
          <div>
            <div className="text-sm font-black tracking-tight">{typeLabel}</div>
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
              {entries.length} 条知识
            </div>
          </div>
        </div>
        <Button
          size="sm"
          className="h-8 rounded-full bg-primary px-4 text-[10px] font-black uppercase shadow-md"
          onClick={handleCreateKnowledge}
        >
          <Plus className="mr-1.5 h-3 w-3" />
          {entryType === "question_sql"
            ? t("kb.training.actions.createQuestionSql")
            : t("kb.training.actions.createDocumentation")}
        </Button>
      </div>

      <main className="flex flex-1 overflow-hidden">
        <aside className="flex w-96 shrink-0 flex-col border-r bg-card">
          <div className="border-b p-5">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground opacity-50" />
              <Input
                value={searchTerm}
                onChange={event => setSearchTerm(event.target.value)}
                placeholder={t("kb.training.searchPlaceholder")}
                className="h-9 rounded-xl bg-zinc-50/50 pl-9 text-xs"
              />
            </div>
          </div>
          <div className="flex-1 space-y-1 overflow-y-auto p-3">
            {filteredEntries.length === 0 ? (
              <div className="p-6 text-center text-sm text-muted-foreground">
                {t("kb.training.emptyByType", { type: typeLabel })}
              </div>
            ) : (
              filteredEntries.map(item => (
                <button
                  key={item.id}
                  onClick={() => setSelectedItemId(item.id)}
                  className={cn(
                    "group flex w-full flex-col gap-2 rounded-[1.5rem] border border-transparent p-4 text-left transition-all",
                    selectedItemId === item.id
                      ? "ring-1 ring-black/5 bg-white shadow-md dark:border-zinc-800 dark:bg-zinc-900"
                      : "hover:bg-muted/50"
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 space-y-1">
                      <span
                        className={cn(
                          "line-clamp-2 text-xs font-black leading-tight",
                          selectedItemId === item.id ? "text-primary" : "text-foreground"
                        )}
                      >
                        {item.title || item.entry_code}
                      </span>
                      {entryType === "question_sql" &&
                      (promotedAssetsByEntryId[item.id] || []).length > 0 ? (
                        <div className="text-[10px] font-bold text-emerald-600">
                          已提升 {(promotedAssetsByEntryId[item.id] || []).length} 个资产
                        </div>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <Badge
                        variant="outline"
                        className={cn(
                          "h-4 px-1 text-[8px] font-black uppercase",
                          getLifecycleTone(item.lifecycle_status)
                        )}
                      >
                        {t(`kb.training.lifecycle.${item.lifecycle_status}`)}
                      </Badge>
                      {entryType === "question_sql" &&
                      (promotedAssetsByEntryId[item.id] || []).length > 0 ? (
                        <Badge
                          variant="outline"
                          className="h-4 px-1 text-[8px] font-black uppercase text-emerald-600"
                        >
                          Asset
                        </Badge>
                      ) : null}
                    </div>
                  </div>
                  <div className="flex items-center justify-between text-[10px] font-bold text-muted-foreground">
                    <span className="font-mono opacity-60">{item.entry_code}</span>
                    <span>{formatDate(item.updated_at)}</span>
                  </div>
                </button>
              ))
            )}
          </div>
        </aside>

        <section className="flex flex-1 flex-col overflow-hidden bg-white dark:bg-zinc-950">
          {selectedItem && detail ? (
            <>
              <div className="shrink-0 space-y-8 border-b bg-card/20 p-10">
                <div className="flex items-start justify-between">
                  <div className="space-y-3">
                    <div className="flex items-center gap-3">
                      <Badge className="border-none bg-primary/10 px-2 py-0 text-[10px] font-black uppercase text-primary">
                        {typeLabel}
                      </Badge>
                      <span className="text-[10px] font-mono font-bold tracking-widest text-muted-foreground">
                        {selectedItem.entry_code}
                      </span>
                    </div>
                    <h2 className="max-w-2xl text-3xl font-black leading-tight tracking-tight">
                      {selectedItem.title || selectedItem.entry_code}
                    </h2>
                    {entryType === "question_sql" &&
                    selectedPromotedAssets.length > 0 ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge
                          variant="outline"
                          className="rounded-full border-emerald-200 bg-emerald-500/10 text-emerald-600"
                        >
                          已提升为 {selectedPromotedAssets.length} 个 SQL 资产
                        </Badge>
                        {selectedPromotedAssets.map(asset => (
                          <Badge key={asset.id} variant="outline">
                            {asset.asset_code}
                          </Badge>
                        ))}
                      </div>
                    ) : null}
                  </div>
                  {entryType === "question_sql" ? (
                    <div className="flex items-center gap-3">
                      {selectedPromotedAssets.length > 0 ? (
                        <Button
                          variant="outline"
                          className="rounded-full px-4 text-[10px] font-black uppercase"
                          onClick={() =>
                            router.push(
                              `/knowledge-bases/${kbId}/assets?entryId=${selectedItem.id}`
                            )
                          }
                        >
                          查看 SQL 资产
                        </Button>
                      ) : null}
                      <Button
                        variant="outline"
                        className="rounded-full px-4 text-[10px] font-black uppercase"
                        onClick={() => setPromotingEntry(selectedItem)}
                      >
                        {selectedPromotedAssets.length > 0
                          ? "继续提升为 SQL 资产"
                          : "提升为 SQL 资产"}
                      </Button>
                    </div>
                  ) : null}
                </div>

                <div className="grid grid-cols-4 gap-8 rounded-[2.5rem] border-2 border-dashed border-zinc-200/50 bg-zinc-50 p-8 dark:border-zinc-800 dark:bg-zinc-900">
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2 text-[9px] font-black uppercase tracking-[0.2em] text-muted-foreground">
                      <Clock className="h-3 w-3 opacity-50" /> {t("kb.training.detail.lifecycle")}
                    </div>
                    <div className="text-xs font-black capitalize">
                      {t(`kb.training.lifecycle.${selectedItem.lifecycle_status}`)}
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2 text-[9px] font-black uppercase tracking-[0.2em] text-muted-foreground">
                      <CheckCircle2 className="h-3 w-3 opacity-50" /> {t("kb.training.detail.quality")}
                    </div>
                    <div className="flex items-center gap-2 text-xs font-black">
                      <span
                        className={cn(
                          "h-1.5 w-1.5 rounded-full",
                          selectedItem.quality_status === "verified"
                            ? "bg-emerald-500"
                            : "bg-amber-500"
                        )}
                      />
                      <span className="capitalize">
                        {t(`kb.training.quality.${selectedItem.quality_status || "unknown"}`)}
                      </span>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <div className="text-[9px] font-black uppercase tracking-[0.2em] text-muted-foreground">
                      {t("kb.training.detail.schemaTable")}
                    </div>
                    <div className="text-xs font-black">
                      {[selectedItem.schema_name, selectedItem.table_name].filter(Boolean).join(".") ||
                        t("kb.training.detail.unbound")}
                    </div>
                  </div>
                  <div className="space-y-1.5 text-right">
                    <div className="text-[9px] font-black uppercase tracking-[0.2em] text-muted-foreground">
                      {t("kb.training.detail.sourceOrigin")}
                    </div>
                    <div className="text-xs font-black uppercase opacity-60">
                      {t(`kb.training.sourceKind.${selectedItem.source_kind || "unknown"}`)}
                    </div>
                  </div>
                </div>
              </div>

              <div className="mx-auto flex w-full max-w-5xl flex-1 overflow-auto p-10">
                <div className="w-full space-y-10">
                  <div className="space-y-4">
                    <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-muted-foreground">
                      {detail.primaryLabel}
                    </h3>
                    <div className="rounded-[2rem] border-2 border-zinc-100 bg-zinc-50 p-8 text-base font-medium leading-relaxed shadow-inner">
                      {detail.primaryBody}
                    </div>
                  </div>

                  {detail.secondaryBody ? (
                    <div className="space-y-4">
                      <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-muted-foreground">
                        {detail.secondaryLabel}
                      </h3>
                      <div
                        className={cn(
                          "rounded-[2.5rem] p-8 shadow-2xl",
                          detail.secondaryIsCode
                            ? "bg-zinc-900 font-mono text-sm leading-relaxed text-zinc-100 ring-8 ring-zinc-900/5"
                            : "border-2 border-zinc-100 bg-zinc-50"
                        )}
                      >
                        {detail.secondaryIsCode ? (
                          <pre className="whitespace-pre-wrap break-all">{detail.secondaryBody}</pre>
                        ) : (
                          detail.secondaryBody
                        )}
                      </div>
                    </div>
                  ) : null}

                  {detail.tertiaryBody ? (
                    <div className="space-y-4">
                      <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-muted-foreground">
                        {detail.tertiaryLabel}
                      </h3>
                      <div className="rounded-[2rem] border bg-card p-6 text-sm leading-relaxed text-muted-foreground">
                        {detail.tertiaryBody}
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
              {t("kb.training.emptyDetail")}
            </div>
          )}
        </section>
      </main>

      <SqlAssetPromoteDialog
        open={Boolean(promotingEntry)}
        onOpenChange={open => {
          if (!open) {
            setPromotingEntry(null)
          }
        }}
        source={
          promotingEntry
            ? { kind: "training_entry", row: promotingEntry }
            : null
        }
        onSuccess={() => void loadData(false)}
      />
    </div>
  )
}
