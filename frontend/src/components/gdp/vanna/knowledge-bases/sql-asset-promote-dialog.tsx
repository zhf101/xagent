"use client"

import React from "react"
import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

import {
  promoteAskRunToSqlAsset,
  promoteTrainingEntryToSqlAsset,
} from "../shared/vanna-api"
import type { VannaAskRunRecord, VannaTrainingEntryRecord } from "../shared/vanna-types"

type PromoteSource =
  | {
      kind: "ask_run"
      row: VannaAskRunRecord
    }
  | {
      kind: "training_entry"
      row: VannaTrainingEntryRecord
    }

interface SqlAssetPromoteDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  source: PromoteSource | null
  onSuccess?: () => void
}

type FormState = {
  assetCode: string
  name: string
  description: string
  intentSummary: string
  keywordsText: string
}

function slugifyAssetCode(value: string) {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/['"]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_")
  return normalized
}

function splitKeywords(value: string) {
  return value
    .split(/[\n,，]/)
    .map(item => item.trim())
    .filter(Boolean)
}

function buildInitialFormState(source: PromoteSource | null): FormState {
  if (!source) {
    return {
      assetCode: "",
      name: "",
      description: "",
      intentSummary: "",
      keywordsText: "",
    }
  }

  if (source.kind === "ask_run") {
    const name = source.row.question_text.trim() || `Ask Run ${source.row.id}`
    return {
      assetCode: slugifyAssetCode(name) || `ask_run_${source.row.id}`,
      name,
      description: `由 Ask 记录 #${source.row.id} 提升而来`,
      intentSummary: source.row.question_text.trim(),
      keywordsText: source.row.question_text.trim(),
    }
  }

  const name =
    (source.row.title || source.row.question_text || "").trim() ||
    `Training Entry ${source.row.id}`
  const keywordSeed = [source.row.title, source.row.question_text]
    .filter(Boolean)
    .join(", ")
  return {
    assetCode: slugifyAssetCode(name) || `training_entry_${source.row.id}`,
    name,
    description: `由训练知识 #${source.row.id} 提升而来`,
    intentSummary: (source.row.question_text || source.row.title || "").trim(),
    keywordsText: keywordSeed,
  }
}

export function SqlAssetPromoteDialog({
  open,
  onOpenChange,
  source,
  onSuccess,
}: SqlAssetPromoteDialogProps) {
  const [submitting, setSubmitting] = useState(false)
  const [formState, setFormState] = useState<FormState>(() =>
    buildInitialFormState(source)
  )

  useEffect(() => {
    if (!open) {
      return
    }
    setFormState(buildInitialFormState(source))
  }, [open, source])

  if (!source) {
    return null
  }

  const activeSource = source
  const sourceLabel =
    activeSource.kind === "ask_run"
      ? `Ask 记录 #${activeSource.row.id}`
      : `训练知识 #${activeSource.row.id}`

  async function handleSubmit() {
    const assetCode = formState.assetCode.trim()
    const name = formState.name.trim()
    if (!assetCode) {
      toast.error("资产编码不能为空")
      return
    }
    if (!name) {
      toast.error("资产名称不能为空")
      return
    }

    const matchExamples =
      activeSource.kind === "ask_run"
        ? [activeSource.row.question_text].filter(
            (item): item is string => Boolean(item)
          )
        : [activeSource.row.question_text || activeSource.row.title].filter(
            (item): item is string => Boolean(item)
          )

    const payload = {
      asset_code: assetCode,
      name,
      description: formState.description.trim() || undefined,
      intent_summary: formState.intentSummary.trim() || undefined,
      asset_kind: "query",
      match_keywords: splitKeywords(formState.keywordsText),
      match_examples: matchExamples,
      parameter_schema_json: [],
      render_config_json: {},
      version_label: "v1",
    }

    try {
      setSubmitting(true)
      if (activeSource.kind === "ask_run") {
        await promoteAskRunToSqlAsset(activeSource.row.id, payload)
      } else {
        await promoteTrainingEntryToSqlAsset(activeSource.row.id, payload)
      }
      toast.success("SQL 资产已创建")
      onOpenChange(false)
      onSuccess?.()
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "提升 SQL 资产失败")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>提升为 SQL 资产</DialogTitle>
          <DialogDescription>
            从 {sourceLabel} 创建可复用 SQL 资产与首个版本。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="sql-asset-name">资产名称</Label>
            <Input
              id="sql-asset-name"
              value={formState.name}
              onChange={event =>
                setFormState(current => ({
                  ...current,
                  name: event.target.value,
                }))
              }
              placeholder="例如：查询所有管理员用户"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="sql-asset-code">资产编码</Label>
            <Input
              id="sql-asset-code"
              value={formState.assetCode}
              onChange={event =>
                setFormState(current => ({
                  ...current,
                  assetCode: event.target.value,
                }))
              }
              placeholder="例如：query_admin_users"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="sql-asset-intent">意图摘要</Label>
            <Textarea
              id="sql-asset-intent"
              value={formState.intentSummary}
              onChange={event =>
                setFormState(current => ({
                  ...current,
                  intentSummary: event.target.value,
                }))
              }
              placeholder="一句话说明这个资产解决什么查询意图"
              className="min-h-20 resize-none"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="sql-asset-keywords">匹配关键词</Label>
            <Textarea
              id="sql-asset-keywords"
              value={formState.keywordsText}
              onChange={event =>
                setFormState(current => ({
                  ...current,
                  keywordsText: event.target.value,
                }))
              }
              placeholder="逗号或换行分隔，例如：管理员, admin, 用户列表"
              className="min-h-20 resize-none"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="sql-asset-description">说明</Label>
            <Textarea
              id="sql-asset-description"
              value={formState.description}
              onChange={event =>
                setFormState(current => ({
                  ...current,
                  description: event.target.value,
                }))
              }
              placeholder="补充资产来源、使用边界或注意事项"
              className="min-h-20 resize-none"
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            取消
          </Button>
          <Button onClick={() => void handleSubmit()} disabled={submitting}>
            {submitting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : null}
            创建 SQL 资产
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
