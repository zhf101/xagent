"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import {
  AlertCircle,
  ChevronRight,
  Database,
  Loader2,
  Play,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Select as SelectRadix,
} from "@/components/ui/select-radix"

import {
  commitSchemaHarvest,
  getVannaKnowledgeBase,
  previewSchemaHarvest,
} from "../shared/vanna-api"
import type {
  VannaKnowledgeBaseRecord,
  VannaSchemaHarvestPreviewResult,
} from "../shared/vanna-types"

type HarvestScope = "all" | "schemas" | "tables"

function splitInput(value: string) {
  return value
    .split(",")
    .map(item => item.trim())
    .filter(Boolean)
}

export function KnowledgeBaseHarvestView() {
  const params = useParams()
  const router = useRouter()
  const kbId = Number(params.id)

  const [loading, setLoading] = useState(true)
  const [kb, setKb] = useState<VannaKnowledgeBaseRecord | null>(null)
  const [scope, setScope] = useState<HarvestScope>("all")
  const [inputValue, setInputValue] = useState("")
  const [previewing, setPreviewing] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [preview, setPreview] = useState<VannaSchemaHarvestPreviewResult | null>(null)

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

  function buildPayload() {
    const items = splitInput(inputValue)
    if (scope === "schemas") {
      return {
        schema_names: items,
        table_names: [],
      }
    }
    if (scope === "tables") {
      return {
        schema_names: [],
        table_names: items,
      }
    }
    return {
      schema_names: [],
      table_names: [],
    }
  }

  async function handlePreview() {
    if (!kb) {
      return
    }
    setPreviewing(true)
    try {
      const payload = buildPayload()
      if (scope !== "all" && payload.schema_names.length === 0 && payload.table_names.length === 0) {
        toast.error("请先填写采集范围")
        return
      }
      const result = await previewSchemaHarvest({
        datasource_id: kb.datasource_id,
        ...payload,
      })
      setPreview(result)
      toast.success("采集范围预览完成")
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "采集预览失败")
    } finally {
      setPreviewing(false)
    }
  }

  async function handleCommit() {
    if (!kb) {
      return
    }
    setCommitting(true)
    try {
      const result = await commitSchemaHarvest({
        datasource_id: kb.datasource_id,
        ...buildPayload(),
      })
      toast.success(`采集任务已提交，写入 ${result.table_count} 张表`)
      router.push(`/gdp/vanna/knowledge-bases/${kb.id}/facts`)
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "采集任务提交失败")
    } finally {
      setCommitting(false)
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
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10">
            <Database className="h-4 w-4 text-primary" />
          </div>
          <div className="flex flex-col">
            <h1 className="text-base font-bold tracking-tight">发起结构采集</h1>
            <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
              {kb.kb_code}
            </div>
          </div>
        </div>
        <Badge variant="outline">
          {kb.system_short}/{kb.env}
        </Badge>
      </header>

      <main className="flex flex-1 justify-center overflow-y-auto p-8">
        <div className="w-full max-w-5xl space-y-8">
          <div className="flex items-center justify-center gap-4">
            <div className="flex items-center gap-2 text-sm font-bold text-primary">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-xs text-white">
                1
              </div>
              配置采集范围
            </div>
            <div className="h-px w-12 bg-border" />
            <div className="flex items-center gap-2 text-sm font-bold text-primary">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-xs text-white">
                2
              </div>
              预览与确认
            </div>
          </div>

          <div className="space-y-8 rounded-[2rem] border bg-card p-8 shadow-sm">
            <div className="space-y-2">
              <h2 className="text-xl font-black">配置本次采集范围</h2>
              <p className="text-sm text-muted-foreground">
                采集会覆盖当前知识库的结构事实层，若源端对象消失，会标记为 STALE 而不是直接删除。
              </p>
            </div>

            <div className="grid gap-6">
              <div className="space-y-3">
                <Label className="text-xs font-black uppercase tracking-wider">
                  采集策略
                </Label>
                <SelectRadix
                  value={scope}
                  onValueChange={value => {
                    setScope(value as HarvestScope)
                    setPreview(null)
                  }}
                >
                  <SelectTrigger className="h-12 rounded-xl bg-muted/30">
                    <SelectValue placeholder="选择范围" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全量采集</SelectItem>
                    <SelectItem value="schemas">按 Schema 采集</SelectItem>
                    <SelectItem value="tables">按表名采集</SelectItem>
                  </SelectContent>
                </SelectRadix>
              </div>

              {scope !== "all" ? (
                <div className="space-y-3">
                  <Label className="text-xs font-black uppercase tracking-wider">
                    {scope === "schemas" ? "Schema 清单" : "表名清单"}
                  </Label>
                  <Input
                    value={inputValue}
                    onChange={event => {
                      setInputValue(event.target.value)
                      setPreview(null)
                    }}
                    className="h-12 rounded-xl"
                    placeholder={
                      scope === "schemas"
                        ? "例如：public, crm, ods"
                        : "例如：orders, order_items, dim_customer"
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    多个名称使用英文逗号分隔。表名按库里真实对象名匹配。
                  </p>
                </div>
              ) : null}

              <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-5 text-sm text-amber-700">
                <div className="flex items-start gap-3">
                  <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                  <div className="space-y-1">
                    <div className="font-bold">采集写入内容</div>
                    <div className="text-xs leading-relaxed">
                      会同步表注释、字段注释、默认值、主外键、DDL、枚举值等结构事实，并按
                      `system_short` 与 `env` 写入当前知识库。
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex justify-end">
                <Button
                  className="h-11 rounded-full px-8 shadow-md"
                  onClick={() => void handlePreview()}
                  disabled={previewing}
                >
                  {previewing ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <ChevronRight className="mr-2 h-4 w-4" />
                  )}
                  预览采集范围
                </Button>
              </div>
            </div>

            {preview ? (
              <div className="space-y-6 border-t border-dashed pt-8">
                <div className="space-y-2">
                  <h2 className="text-xl font-black">预览结果</h2>
                  <p className="text-sm text-muted-foreground">
                    本次采集将落到数据源 {preview.system_short}/{preview.env}。
                  </p>
                </div>

                <div className="grid grid-cols-3 gap-4">
                  <div className="rounded-2xl border border-blue-500/20 bg-blue-500/5 p-5 text-center">
                    <div className="mb-1 text-xs font-bold uppercase tracking-wider text-blue-700">
                      命中 Schema 数
                    </div>
                    <div className="text-3xl font-black text-blue-600">
                      {preview.selected_schema_names.length}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-indigo-500/20 bg-indigo-500/5 p-5 text-center">
                    <div className="mb-1 text-xs font-bold uppercase tracking-wider text-indigo-700">
                      命中表数
                    </div>
                    <div className="text-3xl font-black text-indigo-600">
                      {preview.tables.length}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-5 text-center">
                    <div className="mb-1 text-xs font-bold uppercase tracking-wider text-emerald-700">
                      数据库类型
                    </div>
                    <div className="text-3xl font-black text-emerald-600">
                      {preview.db_type}
                    </div>
                  </div>
                </div>

                <div className="rounded-2xl border bg-background">
                  <div className="border-b px-5 py-4 text-sm font-bold">命中表清单</div>
                  <div className="max-h-80 overflow-y-auto">
                    {preview.tables.length === 0 ? (
                      <div className="p-6 text-sm text-muted-foreground">未命中任何表。</div>
                    ) : (
                      preview.tables.map(item => (
                        <div
                          key={`${item.schema_name}.${item.table_name}`}
                          className="flex items-center justify-between border-b px-5 py-4 text-sm last:border-b-0"
                        >
                          <div>
                            <div className="font-mono font-bold">
                              {item.schema_name || "public"}.{item.table_name}
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {item.table_comment || "暂无表注释"}
                            </div>
                          </div>
                          <div className="text-right text-xs text-muted-foreground">
                            <div>{item.column_count} 列</div>
                            <div>PK {item.primary_keys.length} / FK {item.foreign_key_count}</div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                <div className="flex items-center justify-end border-t border-dashed pt-6">
                  <Button
                    className="h-11 rounded-full bg-primary px-10 shadow-xl shadow-primary/20"
                    onClick={() => void handleCommit()}
                    disabled={committing}
                  >
                    {committing ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="mr-2 h-4 w-4" />
                    )}
                    确认发起采集
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </main>
    </div>
  )
}

