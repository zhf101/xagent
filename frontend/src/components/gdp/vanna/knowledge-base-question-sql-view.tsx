"use client"

import React, { useEffect, useMemo, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import {
  Eye,
  Loader2,
  MessageSquare,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
import { useI18n } from "@/contexts/i18n-context"
import { cn, formatDate } from "@/lib/utils"

import {
  deleteTrainingEntry,
  listTrainingEntries,
  listVannaSqlAssets,
  updateTrainingEntry,
} from "./vanna-api"
import { SqlAssetPromoteDialog } from "./sql-asset-promote-dialog"
import type { VannaSqlAssetRecord, VannaTrainingEntryRecord } from "./vanna-types"

function getLifecycleTone(status: string) {
  if (status === "published") {
    return "bg-emerald-500/10 text-emerald-600 border-emerald-200/50"
  }
  if (status === "candidate") {
    return "bg-amber-500/10 text-amber-600 border-amber-200/50"
  }
  return "bg-zinc-500/10 text-zinc-600 border-zinc-200/50"
}

function truncateSql(sqlText?: string | null) {
  const normalized = (sqlText || "").replace(/\s+/g, " ").trim()
  if (!normalized) {
    return "暂无 SQL"
  }
  return normalized.length > 96 ? `${normalized.slice(0, 96)}...` : normalized
}

export function KnowledgeBaseQuestionSqlView() {
  const { t } = useI18n()
  const params = useParams()
  const router = useRouter()
  const kbId = Number(params.id)

  const [loading, setLoading] = useState(true)
  const [entries, setEntries] = useState<VannaTrainingEntryRecord[]>([])
  const [assets, setAssets] = useState<VannaSqlAssetRecord[]>([])
  const [searchTerm, setSearchTerm] = useState("")
  const [detailEntry, setDetailEntry] = useState<VannaTrainingEntryRecord | null>(null)
  const [editingEntry, setEditingEntry] = useState<VannaTrainingEntryRecord | null>(null)
  const [promotingEntry, setPromotingEntry] =
    useState<VannaTrainingEntryRecord | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<VannaTrainingEntryRecord | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [savingEdit, setSavingEdit] = useState(false)
  const [editQuestion, setEditQuestion] = useState("")
  const [editSql, setEditSql] = useState("")
  const [editExplanation, setEditExplanation] = useState("")

  async function loadData(showLoading = true) {
    if (!Number.isFinite(kbId)) {
      return
    }
    if (showLoading) {
      setLoading(true)
    }
    try {
      const [entryRows, assetRows] = await Promise.all([
        listTrainingEntries({ kb_id: kbId, entry_type: "question_sql" }),
        listVannaSqlAssets({ kb_id: kbId }),
      ])
      setEntries(entryRows)
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
    void loadData()
  }, [kbId])

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
          entry.sql_text,
          entry.sql_explanation,
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

  async function handleDeleteConfirm() {
    if (!deleteTarget) {
      return
    }
    try {
      setDeleting(true)
      await deleteTrainingEntry(deleteTarget.id)
      toast.success("SQL 问答对已删除")
      setDeleteTarget(null)
      if (detailEntry?.id === deleteTarget.id) {
        setDetailEntry(null)
      }
      await loadData(false)
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "删除 SQL 问答对失败")
    } finally {
      setDeleting(false)
    }
  }

  function handleEditOpen(entry: VannaTrainingEntryRecord) {
    setEditingEntry(entry)
    setEditQuestion(entry.question_text || "")
    setEditSql(entry.sql_text || "")
    setEditExplanation(entry.sql_explanation || "")
  }

  async function handleEditSave() {
    if (!editingEntry) {
      return
    }
    if (!editQuestion.trim() || !editSql.trim()) {
      toast.error("问题和 SQL 不能为空")
      return
    }

    try {
      setSavingEdit(true)
      const updated = await updateTrainingEntry(editingEntry.id, {
        question: editQuestion.trim(),
        sql: editSql.trim(),
        sql_explanation: editExplanation.trim() || undefined,
      })
      setEntries(current =>
        current.map(entry => (entry.id === updated.id ? updated : entry))
      )
      if (detailEntry?.id === updated.id) {
        setDetailEntry(updated)
      }
      setEditingEntry(null)
      toast.success("SQL 问答对已更新")
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "修改 SQL 问答对失败")
    } finally {
      setSavingEdit(false)
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
    <div className="flex h-[calc(100vh-112px)] w-full flex-col overflow-hidden bg-[linear-gradient(180deg,#fff_0%,#f8fafc_100%)]">
      <div className="z-10 flex shrink-0 items-center justify-between border-b bg-white/90 px-8 py-5 backdrop-blur">
        <div className="flex items-center gap-4">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10">
            <MessageSquare className="h-4 w-4 text-primary" />
          </div>
          <div>
            <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.28em] text-muted-foreground">
              <Sparkles className="h-3.5 w-3.5" />
              SQL QA Pairs
            </div>
            <div className="mt-1 text-base font-black tracking-tight">
              SQL 问答对列表
            </div>
            <div className="text-xs text-muted-foreground">
              先看列表，再在每一行直接操作详情、提升、删除和修改
            </div>
          </div>
        </div>
        <Button
          size="sm"
          className="h-9 rounded-full bg-primary px-5 text-[11px] font-black uppercase shadow-md"
          onClick={() => router.push(`/knowledge-bases/${kbId}/training/question-sql/new`)}
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          新建问答对
        </Button>
      </div>

      <div className="flex shrink-0 items-center justify-between gap-4 border-b bg-white/70 px-8 py-4">
        <div className="relative w-full max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchTerm}
            onChange={event => setSearchTerm(event.target.value)}
            placeholder="搜索问题、SQL、表名或问答对编码..."
            className="h-10 rounded-2xl border-none bg-zinc-100/90 pl-9 text-sm shadow-inner"
          />
        </div>
        <Badge variant="outline" className="rounded-full px-3 py-1 text-[11px] font-bold">
          共 {filteredEntries.length} 条
        </Badge>
      </div>

      <div className="flex-1 overflow-auto px-8 py-6">
        <div className="overflow-hidden rounded-[1.75rem] border bg-white shadow-[0_20px_60px_rgba(15,23,42,0.06)]">
          <Table>
            <TableHeader className="bg-zinc-50/80">
              <TableRow className="hover:bg-zinc-50/80">
                <TableHead className="w-[28%]">问答对</TableHead>
                <TableHead className="w-[30%]">SQL 摘要</TableHead>
                <TableHead className="w-[10%]">状态</TableHead>
                <TableHead className="w-[14%]">已提升资产</TableHead>
                <TableHead className="w-[10%]">更新时间</TableHead>
                <TableHead className="w-[20%] text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredEntries.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-12 text-center text-sm text-muted-foreground">
                    当前没有可展示的 SQL 问答对。
                  </TableCell>
                </TableRow>
              ) : (
                filteredEntries.map(entry => {
                  const promotedAssets = promotedAssetsByEntryId[entry.id] || []
                  return (
                    <TableRow key={entry.id}>
                      <TableCell className="align-top">
                        <div className="space-y-2">
                          <div className="line-clamp-2 text-sm font-black leading-6">
                            {entry.question_text || entry.title || entry.entry_code}
                          </div>
                          <div className="text-[11px] font-mono text-muted-foreground">
                            {entry.entry_code}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="align-top">
                        <div className="max-w-xl space-y-2">
                          <div className="line-clamp-2 font-mono text-xs leading-5 text-zinc-700">
                            {truncateSql(entry.sql_text)}
                          </div>
                          {entry.sql_explanation ? (
                            <div className="line-clamp-1 text-xs text-muted-foreground">
                              {entry.sql_explanation}
                            </div>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge
                          variant="outline"
                          className={cn("rounded-full", getLifecycleTone(entry.lifecycle_status))}
                        >
                          {t(`kb.training.lifecycle.${entry.lifecycle_status}`)}
                        </Badge>
                      </TableCell>
                      <TableCell className="align-top">
                        {promotedAssets.length > 0 ? (
                          <div className="space-y-1">
                            <div className="text-sm font-bold text-emerald-600">
                              {promotedAssets.length} 个
                            </div>
                            <div className="line-clamp-2 text-xs text-muted-foreground">
                              {promotedAssets.map(asset => asset.asset_code).join(", ")}
                            </div>
                          </div>
                        ) : (
                          <span className="text-sm text-muted-foreground">未提升</span>
                        )}
                      </TableCell>
                      <TableCell className="align-top text-sm text-muted-foreground">
                        {formatDate(entry.updated_at)}
                      </TableCell>
                      <TableCell className="align-top">
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            className="rounded-full"
                            onClick={() => setDetailEntry(entry)}
                          >
                            <Eye className="mr-1 h-3.5 w-3.5" />
                            查看详情
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="rounded-full"
                            onClick={() => setPromotingEntry(entry)}
                          >
                            提升为 SQL 资产
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="rounded-full"
                            onClick={() => handleEditOpen(entry)}
                          >
                            <Pencil className="mr-1 h-3.5 w-3.5" />
                            修改问答对
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="rounded-full text-red-600 hover:text-red-600"
                            onClick={() => setDeleteTarget(entry)}
                          >
                            <Trash2 className="mr-1 h-3.5 w-3.5" />
                            删除问答对
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      <Dialog open={Boolean(detailEntry)} onOpenChange={open => !open && setDetailEntry(null)}>
        <DialogContent className="max-w-4xl">
          {detailEntry ? (
            <>
              <DialogHeader>
                <DialogTitle>SQL 问答对详情</DialogTitle>
                <DialogDescription>
                  查看完整问题、标准 SQL、补充说明与提升状态。
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-6">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className={getLifecycleTone(detailEntry.lifecycle_status)}>
                    {t(`kb.training.lifecycle.${detailEntry.lifecycle_status}`)}
                  </Badge>
                  <Badge variant="outline">{detailEntry.entry_code}</Badge>
                  <Badge variant="outline">
                    {(promotedAssetsByEntryId[detailEntry.id] || []).length > 0
                      ? `已提升 ${(promotedAssetsByEntryId[detailEntry.id] || []).length} 个资产`
                      : "未提升为 SQL 资产"}
                  </Badge>
                </div>

                <div className="space-y-2">
                  <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                    用户问题
                  </div>
                  <div className="rounded-3xl border bg-zinc-50 p-5 text-sm leading-7">
                    {detailEntry.question_text || "暂无问题文本"}
                  </div>
                </div>

                <div className="space-y-2">
                  <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                    标准 SQL
                  </div>
                  <pre className="overflow-auto rounded-3xl bg-zinc-950 p-5 font-mono text-xs leading-6 text-zinc-100">
                    {detailEntry.sql_text || "暂无 SQL"}
                  </pre>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                      补充说明
                    </div>
                    <div className="min-h-28 rounded-3xl border bg-white p-5 text-sm leading-7">
                      {detailEntry.sql_explanation || "暂无补充说明"}
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                      已提升资产
                    </div>
                    <div className="min-h-28 rounded-3xl border bg-white p-5">
                      {(promotedAssetsByEntryId[detailEntry.id] || []).length > 0 ? (
                        <div className="flex flex-wrap gap-2">
                          {(promotedAssetsByEntryId[detailEntry.id] || []).map(asset => (
                            <Badge key={asset.id} variant="outline">
                              {asset.asset_code}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <div className="text-sm text-muted-foreground">当前没有对应 SQL 资产。</div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(editingEntry)}
        onOpenChange={open => {
          if (!open && !savingEdit) {
            setEditingEntry(null)
          }
        }}
      >
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>修改 SQL 问答对</DialogTitle>
            <DialogDescription>直接在当前页面更新问题、SQL 和补充说明。</DialogDescription>
          </DialogHeader>
          <div className="space-y-5">
            <div className="space-y-2">
              <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                用户问题
              </div>
              <Input
                value={editQuestion}
                onChange={event => setEditQuestion(event.target.value)}
                placeholder="例如：查询所有管理员用户"
                disabled={savingEdit}
              />
            </div>
            <div className="space-y-2">
              <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                标准 SQL
              </div>
              <Textarea
                value={editSql}
                onChange={event => setEditSql(event.target.value)}
                placeholder="SELECT * FROM users WHERE role = 'admin'"
                className="min-h-[220px] font-mono text-sm"
                disabled={savingEdit}
              />
            </div>
            <div className="space-y-2">
              <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                补充说明
              </div>
              <Textarea
                value={editExplanation}
                onChange={event => setEditExplanation(event.target.value)}
                placeholder="补充这个问答对的使用边界和说明"
                className="min-h-28"
                disabled={savingEdit}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setEditingEntry(null)}
              disabled={savingEdit}
            >
              取消
            </Button>
            <Button onClick={() => void handleEditSave()} disabled={savingEdit}>
              {savingEdit ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              保存修改
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <SqlAssetPromoteDialog
        open={Boolean(promotingEntry)}
        onOpenChange={open => !open && setPromotingEntry(null)}
        source={
          promotingEntry
            ? {
                kind: "training_entry",
                row: promotingEntry,
              }
            : null
        }
        onSuccess={() => void loadData(false)}
      />

      <ConfirmDialog
        isOpen={Boolean(deleteTarget)}
        onOpenChange={open => !open && setDeleteTarget(null)}
        onConfirm={() => void handleDeleteConfirm()}
        isLoading={deleting}
        title="删除 SQL 问答对"
        description={
          deleteTarget
            ? `确认删除“${deleteTarget.question_text || deleteTarget.entry_code}”吗？`
            : ""
        }
        confirmText="确认删除"
      />
    </div>
  )
}
