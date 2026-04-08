"use client"

import { useEffect, useMemo, useState } from "react"
import { Loader2, Save, Settings2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Textarea } from "@/components/ui/textarea"

import { createVannaKnowledgeBase } from "../shared/vanna-api"
import type { VannaKnowledgeBaseRecord } from "../shared/vanna-types"

interface KnowledgeBaseSettingsSheetProps {
  kb: VannaKnowledgeBaseRecord | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: (nextKb: VannaKnowledgeBaseRecord) => void
}

type FormState = {
  name: string
  description: string
  defaultTopKSql: string
  defaultTopKSchema: string
  defaultTopKDoc: string
}

function buildFormState(kb: VannaKnowledgeBaseRecord | null): FormState {
  return {
    name: kb?.name ?? "",
    description: kb?.description ?? "",
    defaultTopKSql:
      kb?.default_top_k_sql !== null && kb?.default_top_k_sql !== undefined
        ? String(kb.default_top_k_sql)
        : "",
    defaultTopKSchema:
      kb?.default_top_k_schema !== null && kb?.default_top_k_schema !== undefined
        ? String(kb.default_top_k_schema)
        : "",
    defaultTopKDoc:
      kb?.default_top_k_doc !== null && kb?.default_top_k_doc !== undefined
        ? String(kb.default_top_k_doc)
        : "",
  }
}

function parseOptionalPositiveInteger(value: string, label: string) {
  const normalized = value.trim()
  if (!normalized) {
    return undefined
  }
  const parsed = Number(normalized)
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${label}必须是正整数`)
  }
  return parsed
}

export function KnowledgeBaseSettingsSheet({
  kb,
  open,
  onOpenChange,
  onSaved,
}: KnowledgeBaseSettingsSheetProps) {
  const [saving, setSaving] = useState(false)
  const [formState, setFormState] = useState<FormState>(() => buildFormState(kb))

  useEffect(() => {
    if (!open) {
      return
    }
    setFormState(buildFormState(kb))
  }, [kb, open])

  const datasourceSummary = useMemo(() => {
    if (!kb) {
      return "加载中"
    }
    return `${kb.datasource_name || `#${kb.datasource_id}`} / ${kb.system_short} / ${kb.database_name || "-"} / ${kb.env}`
  }, [kb])

  function updateField<Key extends keyof FormState>(key: Key, value: FormState[Key]) {
    setFormState(current => ({
      ...current,
      [key]: value,
    }))
  }

  async function handleSave() {
    if (!kb) {
      return
    }

    const nextName = formState.name.trim()
    if (!nextName) {
      toast.error("知识库名称不能为空")
      return
    }

    try {
      setSaving(true)
      const nextKb = await createVannaKnowledgeBase({
        datasource_id: kb.datasource_id,
        name: nextName,
        description: formState.description.trim(),
        default_top_k_sql: parseOptionalPositiveInteger(
          formState.defaultTopKSql,
          "SQL 召回条数"
        ),
        default_top_k_schema: parseOptionalPositiveInteger(
          formState.defaultTopKSchema,
          "表结构召回条数"
        ),
        default_top_k_doc: parseOptionalPositiveInteger(
          formState.defaultTopKDoc,
          "文档召回条数"
        ),
      })
      onSaved(nextKb)
      onOpenChange(false)
      toast.success("知识库设置已保存")
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "保存知识库设置失败")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[92vw] sm:max-w-2xl p-0 gap-0">
        <SheetHeader className="border-b px-6 py-4 pr-14 shrink-0">
          <SheetTitle className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            知识库设置
          </SheetTitle>
          <SheetDescription>
            调整知识库名称、检索默认参数和模型配置。保存后会直接作用于当前默认知识库。
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="space-y-6">
            <section className="rounded-2xl border bg-muted/30 p-4">
              <div className="text-xs font-bold text-muted-foreground">关联数据源</div>
              <div className="mt-1 text-sm font-medium">{datasourceSummary}</div>
              {kb ? (
                <div className="mt-2 text-xs text-muted-foreground">
                  KB Code: {kb.kb_code}
                </div>
              ) : null}
            </section>

            <section className="space-y-4">
              <div className="text-sm font-semibold">基础信息</div>
              <div className="grid gap-4">
                <div className="space-y-2">
                  <Label htmlFor="kb-settings-name">知识库名称</Label>
                  <Input
                    id="kb-settings-name"
                    value={formState.name}
                    onChange={event => updateField("name", event.target.value)}
                    placeholder="输入知识库名称"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="kb-settings-description">知识库描述</Label>
                  <Textarea
                    id="kb-settings-description"
                    value={formState.description}
                    onChange={event => updateField("description", event.target.value)}
                    placeholder="补充业务域、使用范围或训练策略"
                    className="min-h-24 resize-none"
                  />
                </div>
              </div>
            </section>

            <section className="space-y-4">
              <div className="text-sm font-semibold">默认检索参数</div>
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="kb-settings-topk-sql">SQL 召回条数</Label>
                  <Input
                    id="kb-settings-topk-sql"
                    inputMode="numeric"
                    value={formState.defaultTopKSql}
                    onChange={event => updateField("defaultTopKSql", event.target.value)}
                    placeholder="例如 5"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="kb-settings-topk-schema">表结构召回条数</Label>
                  <Input
                    id="kb-settings-topk-schema"
                    inputMode="numeric"
                    value={formState.defaultTopKSchema}
                    onChange={event => updateField("defaultTopKSchema", event.target.value)}
                    placeholder="例如 8"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="kb-settings-topk-doc">文档召回条数</Label>
                  <Input
                    id="kb-settings-topk-doc"
                    inputMode="numeric"
                    value={formState.defaultTopKDoc}
                    onChange={event => updateField("defaultTopKDoc", event.target.value)}
                    placeholder="例如 5"
                  />
                </div>
              </div>
            </section>
          </div>
        </div>

        <SheetFooter className="border-t px-6 py-4 shrink-0 sm:flex-row sm:justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            取消
          </Button>
          <Button onClick={() => void handleSave()} disabled={!kb || saving}>
            {saving ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            保存设置
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
