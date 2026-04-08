"use client"

import React, { useEffect, useMemo, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import {
  CheckCircle2,
  Database,
  Info,
  ListFilter,
  Loader2,
  RotateCcw,
  Save,
  Search,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

import {
  listSchemaColumns,
  listSchemaTables,
  updateSchemaColumnAnnotation,
} from "../shared/vanna-api"
import type {
  VannaSchemaColumnRecord,
  VannaSchemaTableRecord,
} from "../shared/vanna-types"

type ColumnDraft = {
  comment: string
  defaultValue: string
  allowedValuesText: string
  businessDescription: string
}

function normalizeText(value: string | null | undefined) {
  return (value || "").trim()
}

function normalizeList(values: string[]) {
  return (values || []).map(item => item.trim()).filter(Boolean)
}

function parseListText(value: string) {
  return normalizeList(value.split(/[\n,，]/))
}

function joinList(values: string[]) {
  return normalizeList(values).join(", ")
}

function buildHarvestedRangeText(column: VannaSchemaColumnRecord) {
  const allowedValues = column.allowed_values_json || []
  const sampleValues = column.sample_values_json || []
  if (allowedValues.length > 0) {
    return joinList(allowedValues)
  }
  if (sampleValues.length > 0) {
    return `示例值: ${joinList(sampleValues)}`
  }
  return ""
}

function buildEffectiveRangeText(column: VannaSchemaColumnRecord) {
  const allowedValues = column.effective_allowed_values_json || []
  const sampleValues = column.effective_sample_values_json || []
  if (allowedValues.length > 0) {
    return joinList(allowedValues)
  }
  if (sampleValues.length > 0) {
    return `示例值: ${joinList(sampleValues)}`
  }
  return ""
}

function buildDraftFromColumn(column: VannaSchemaColumnRecord): ColumnDraft {
  return {
    comment: column.effective_column_comment || "",
    defaultValue: column.effective_default_raw || "",
    allowedValuesText: joinList(column.effective_allowed_values_json || []),
    businessDescription: column.business_description || "",
  }
}

function buildHarvestedDraft(column: VannaSchemaColumnRecord): ColumnDraft {
  return {
    comment: column.column_comment || "",
    defaultValue: column.default_raw || "",
    allowedValuesText: joinList(column.allowed_values_json || []),
    businessDescription: "",
  }
}

function listsEqual(left: string[], right: string[]) {
  if (left.length !== right.length) {
    return false
  }
  return left.every((item, index) => item === right[index])
}

function getStatusTone(status: string) {
  if (status === "active") {
    return "bg-emerald-500/10 text-emerald-600 border-emerald-200"
  }
  if (status === "stale") {
    return "bg-amber-500/10 text-amber-600 border-amber-200"
  }
  return "bg-zinc-500/10 text-zinc-600 border-zinc-200"
}

export function KnowledgeBaseFactsView() {
  const params = useParams()
  const router = useRouter()
  const kbId = Number(params.id)

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [tables, setTables] = useState<VannaSchemaTableRecord[]>([])
  const [columns, setColumns] = useState<VannaSchemaColumnRecord[]>([])
  const [selectedTableId, setSelectedTableId] = useState<number | null>(null)
  const [searchTerm, setSearchTerm] = useState("")
  const [drafts, setDrafts] = useState<Record<number, ColumnDraft>>({})

  async function loadData() {
    const [tableRows, columnRows] = await Promise.all([
      listSchemaTables({ kb_id: kbId }),
      listSchemaColumns({ kb_id: kbId }),
    ])
    setTables(tableRows)
    setColumns(columnRows)
  }

  useEffect(() => {
    if (!Number.isFinite(kbId)) {
      return
    }

    let cancelled = false

    async function load() {
      setLoading(true)
      try {
        const [tableRows, columnRows] = await Promise.all([
          listSchemaTables({ kb_id: kbId }),
          listSchemaColumns({ kb_id: kbId }),
        ])
        if (cancelled) {
          return
        }
        setTables(tableRows)
        setColumns(columnRows)
      } catch (error) {
        console.error(error)
        if (!cancelled) {
          toast.error(error instanceof Error ? error.message : "加载结构事实失败")
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [kbId])

  const filteredTables = useMemo(() => {
    const keyword = searchTerm.trim().toLowerCase()
    const sortedTables = [...tables].sort((left, right) => {
      const leftActive = left.status === "active" ? 0 : 1
      const rightActive = right.status === "active" ? 0 : 1
      if (leftActive !== rightActive) {
        return leftActive - rightActive
      }
      const leftName = `${left.schema_name || ""}.${left.table_name}`.toLowerCase()
      const rightName = `${right.schema_name || ""}.${right.table_name}`.toLowerCase()
      return leftName.localeCompare(rightName)
    })

    if (!keyword) {
      return sortedTables
    }

    return sortedTables.filter(table => {
      const haystack = [
        table.schema_name,
        table.table_name,
        table.table_comment,
        table.system_short,
        table.env,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
      return haystack.includes(keyword)
    })
  }, [tables, searchTerm])

  useEffect(() => {
    if (filteredTables.length === 0) {
      setSelectedTableId(null)
      return
    }
    if (
      selectedTableId === null ||
      !filteredTables.some(table => table.id === selectedTableId)
    ) {
      setSelectedTableId(filteredTables[0].id)
    }
  }, [filteredTables, selectedTableId])

  const selectedTable =
    filteredTables.find(table => table.id === selectedTableId) ||
    tables.find(table => table.id === selectedTableId) ||
    null

  const selectedColumns = useMemo(() => {
    if (!selectedTable) {
      return []
    }
    return [...columns]
      .filter(column => column.table_id === selectedTable.id)
      .sort((left, right) => {
        const leftOrder = left.ordinal_position ?? Number.MAX_SAFE_INTEGER
        const rightOrder = right.ordinal_position ?? Number.MAX_SAFE_INTEGER
        if (leftOrder !== rightOrder) {
          return leftOrder - rightOrder
        }
        return left.column_name.localeCompare(right.column_name)
      })
  }, [columns, selectedTable])

  useEffect(() => {
    if (selectedColumns.length === 0) {
      return
    }
    setDrafts(current => {
      const next: Record<number, ColumnDraft> = {}
      selectedColumns.forEach(column => {
        next[column.id] = current[column.id] || buildDraftFromColumn(column)
      })
      return next
    })
  }, [selectedColumns])

  function getDraft(column: VannaSchemaColumnRecord) {
    return drafts[column.id] || buildDraftFromColumn(column)
  }

  function updateDraft(
    column: VannaSchemaColumnRecord,
    patch: Partial<ColumnDraft>
  ) {
    setDrafts(current => ({
      ...current,
      [column.id]: {
        ...(current[column.id] || buildDraftFromColumn(column)),
        ...patch,
      },
    }))
  }

  function restoreHarvestedValues(column: VannaSchemaColumnRecord) {
    updateDraft(column, buildHarvestedDraft(column))
  }

  function isColumnDirty(column: VannaSchemaColumnRecord) {
    const draft = getDraft(column)
    return (
      normalizeText(draft.comment) !== normalizeText(column.effective_column_comment) ||
      normalizeText(draft.defaultValue) !== normalizeText(column.effective_default_raw) ||
      !listsEqual(
        parseListText(draft.allowedValuesText),
        normalizeList(column.effective_allowed_values_json || [])
      ) ||
      normalizeText(draft.businessDescription) !== normalizeText(column.business_description)
    )
  }

  const dirtyColumnIds = useMemo(() => {
    return selectedColumns
      .filter(column => isColumnDirty(column))
      .map(column => column.id)
  }, [selectedColumns, drafts])

  async function handleSaveCurrentTable() {
    if (dirtyColumnIds.length === 0) {
      return
    }

    setSaving(true)
    try {
      await Promise.all(
        selectedColumns
          .filter(column => dirtyColumnIds.includes(column.id))
          .map(column => {
            const draft = getDraft(column)
            const nextAllowedValues = parseListText(draft.allowedValuesText)
            const harvestedAllowedValues = normalizeList(column.allowed_values_json || [])
            const normalizedComment = normalizeText(draft.comment)
            const harvestedComment = normalizeText(column.column_comment)
            const normalizedDefaultValue = normalizeText(draft.defaultValue)
            const harvestedDefaultValue = normalizeText(column.default_raw)

            return updateSchemaColumnAnnotation(column.id, {
              business_description: normalizeText(draft.businessDescription) || null,
              comment_override:
                normalizedComment === harvestedComment ? null : normalizedComment,
              default_value_override:
                normalizedDefaultValue === harvestedDefaultValue
                  ? null
                  : normalizedDefaultValue,
              allowed_values_override_json:
                listsEqual(nextAllowedValues, harvestedAllowedValues)
                  ? null
                  : nextAllowedValues,
              sample_values_override_json:
                (column.sample_values_override_json || []).length > 0
                  ? column.sample_values_override_json || []
                  : null,
              update_source: "manual",
            })
          })
      )

      await loadData()
      setDrafts({})
      toast.success("结构事实补充信息已保存")
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "保存结构事实失败")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-112px)] w-full items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  if (tables.length === 0) {
    return (
      <div className="flex h-[calc(100vh-112px)] w-full items-center justify-center bg-background p-8">
        <div className="max-w-md rounded-[2rem] border border-dashed bg-card p-10 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
            <Database className="h-6 w-6 text-primary" />
          </div>
          <h2 className="text-xl font-black">当前知识库还没有结构事实</h2>
          <p className="mt-3 text-sm text-muted-foreground">
            先发起一次结构采集，页面才会展示该数据源的真实表和字段元数据。
          </p>
          <Button
            className="mt-6 rounded-full px-8"
            onClick={() => router.push(`/gdp/vanna/knowledge-bases/${kbId}/harvest`)}
          >
            去发起采集
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100vh-112px)] w-full overflow-hidden animate-in fade-in duration-500">
      <aside className="flex w-72 shrink-0 flex-col border-r bg-card/50">
        <div className="space-y-4 border-b p-5">
          <div className="flex items-center justify-between">
            <h3 className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-muted-foreground">
              <ListFilter className="h-3 w-3" /> 表清单
            </h3>
            <Badge variant="secondary" className="h-4 px-1.5 text-[9px] font-bold">
              {filteredTables.length}
            </Badge>
          </div>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={searchTerm}
              onChange={event => setSearchTerm(event.target.value)}
              placeholder="搜索表名或注释..."
              className="h-9 rounded-xl border-none bg-background pl-9 text-xs shadow-inner"
            />
          </div>
        </div>
        <div className="flex-1 space-y-1.5 overflow-y-auto p-3">
          {filteredTables.map(table => (
            <button
              key={table.id}
              onClick={() => setSelectedTableId(table.id)}
              className={cn(
                "group flex w-full flex-col gap-1.5 rounded-2xl border border-transparent p-4 text-left transition-all",
                selectedTableId === table.id
                  ? "scale-[1.02] bg-primary text-primary-foreground shadow-lg shadow-primary/20"
                  : "hover:bg-muted/80"
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-xs font-mono font-black">
                  {table.table_name}
                </span>
                <Badge
                  variant="outline"
                  className={cn(
                    "h-4 px-1 text-[8px] uppercase",
                    selectedTableId === table.id
                      ? "border-white/20 bg-white/10 text-primary-foreground"
                      : getStatusTone(table.status)
                  )}
                >
                  {table.status}
                </Badge>
              </div>
              <div
                className={cn(
                  "truncate text-[10px] font-medium italic",
                  selectedTableId === table.id
                    ? "text-primary-foreground/70"
                    : "text-muted-foreground"
                )}
              >
                {(table.schema_name || "public")}.{table.table_comment || "暂无表注释"}
              </div>
            </button>
          ))}
        </div>
      </aside>

      <section className="flex flex-1 flex-col overflow-hidden bg-background">
        {selectedTable ? (
          <>
            <div className="flex shrink-0 items-center justify-between border-b bg-white p-8 dark:bg-zinc-950">
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <Badge className="border-none bg-primary/10 text-[9px] font-black uppercase tracking-[0.2em] text-primary">
                    Structure Facts
                  </Badge>
                  <span className="text-[10px] font-mono font-bold text-muted-foreground opacity-60">
                    {(selectedTable.schema_name || "public").toUpperCase()}
                  </span>
                  <Badge variant="outline" className={getStatusTone(selectedTable.status)}>
                    {selectedTable.status}
                  </Badge>
                </div>
                <h2 className="flex items-center gap-3 text-3xl font-mono font-black tracking-tight">
                  {selectedTable.table_name}
                  <Info className="h-4 w-4 opacity-30" />
                </h2>
                <p className="max-w-3xl text-sm text-muted-foreground">
                  {normalizeText(selectedTable.table_comment) || "暂无表注释"}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <div className="text-right text-xs text-muted-foreground">
                  <div>字段数 {selectedColumns.length}</div>
                  <div>待保存变更 {dirtyColumnIds.length}</div>
                </div>
                <Button
                  className="rounded-full px-6 font-bold"
                  onClick={() => void handleSaveCurrentTable()}
                  disabled={saving || dirtyColumnIds.length === 0}
                >
                  {saving ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="mr-2 h-4 w-4" />
                  )}
                  保存当前表变更
                </Button>
              </div>
            </div>

            <div className="flex-1 overflow-auto p-8">
              <div className="mb-6 flex items-center gap-3 rounded-[2rem] border border-dashed border-zinc-200 bg-zinc-50 px-6 py-4 dark:border-zinc-800 dark:bg-zinc-900/50">
                <CheckCircle2 className="h-4 w-4 text-emerald-600 opacity-80" />
                <p className="text-[11px] italic leading-relaxed text-muted-foreground">
                  当前页面展示的是合并视图：输入框显示当前生效值，灰色提示保留采集原值。保存时只写人工补充层，不会覆盖原始采集快照。
                </p>
              </div>

              <div className="overflow-hidden rounded-[2.5rem] border bg-card shadow-2xl shadow-black/5">
                <Table>
                  <TableHeader className="border-b bg-zinc-50 dark:bg-zinc-900">
                    <TableRow className="border-none hover:bg-transparent">
                      <TableHead className="w-12 text-center text-[10px] font-black uppercase tracking-widest">
                        #
                      </TableHead>
                      <TableHead className="w-[220px] text-[10px] font-black uppercase tracking-widest">
                        物理字段 (Name/Type)
                      </TableHead>
                      <TableHead className="w-[220px] text-[10px] font-black uppercase tracking-widest text-primary">
                        字段注释 (Comment)
                      </TableHead>
                      <TableHead className="w-[180px] text-[10px] font-black uppercase tracking-widest text-primary">
                        默认值 (Default)
                      </TableHead>
                      <TableHead className="w-[220px] text-[10px] font-black uppercase tracking-widest text-primary">
                        取值范围 (Enum)
                      </TableHead>
                      <TableHead className="min-w-[320px] text-[10px] font-black uppercase tracking-widest text-primary">
                        业务说明 (Description)
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {selectedColumns.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                          当前表还没有字段事实。
                        </TableCell>
                      </TableRow>
                    ) : (
                      selectedColumns.map(column => {
                        const draft = getDraft(column)
                        const harvestedRangeText = buildHarvestedRangeText(column)
                        const effectiveRangeText = buildEffectiveRangeText(column)

                        return (
                          <TableRow
                            key={column.id}
                            className="border-zinc-100 align-top transition-colors hover:bg-zinc-50/50 dark:border-zinc-800 dark:hover:bg-zinc-900/50"
                          >
                            <TableCell className="text-center text-[10px] font-mono font-bold text-muted-foreground">
                              {column.ordinal_position ?? "-"}
                            </TableCell>
                            <TableCell>
                              <div className="flex flex-col gap-1">
                                <div className="flex items-center gap-2 font-mono text-xs font-black">
                                  {column.is_primary_key ? (
                                    <Database className="h-3 w-3 text-amber-500" />
                                  ) : null}
                                  {column.column_name}
                                  {column.is_nullable === false ? (
                                    <Badge variant="outline" className="h-4 px-1 text-[8px] uppercase">
                                      not null
                                    </Badge>
                                  ) : null}
                                </div>
                                <div className="text-[9px] font-mono font-black uppercase opacity-50">
                                  {column.data_type || column.udt_name || "unknown"}
                                </div>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  className="mt-2 h-7 justify-start rounded-full px-2 text-[10px] font-bold text-muted-foreground"
                                  onClick={() => restoreHarvestedValues(column)}
                                >
                                  <RotateCcw className="mr-1.5 h-3 w-3" />
                                  恢复采集值
                                </Button>
                              </div>
                            </TableCell>
                            <TableCell>
                              <div className="space-y-2">
                                <Textarea
                                  value={draft.comment}
                                  onChange={event =>
                                    updateDraft(column, {
                                      comment: event.target.value,
                                    })
                                  }
                                  placeholder="填写字段注释"
                                  className="min-h-[72px] resize-none rounded-2xl bg-zinc-50/70 py-2 text-xs"
                                />
                                <div className="text-[10px] leading-relaxed text-muted-foreground">
                                  采集值：
                                  {normalizeText(column.column_comment) || "无"}
                                </div>
                              </div>
                            </TableCell>
                            <TableCell>
                              <div className="space-y-2">
                                <Input
                                  value={draft.defaultValue}
                                  onChange={event =>
                                    updateDraft(column, {
                                      defaultValue: event.target.value,
                                    })
                                  }
                                  placeholder="无"
                                  className="h-9 rounded-xl bg-zinc-50/70 text-xs font-mono"
                                />
                                <div className="text-[10px] leading-relaxed text-muted-foreground">
                                  采集值：
                                  {normalizeText(column.default_raw) || "无"}
                                </div>
                              </div>
                            </TableCell>
                            <TableCell>
                              <div className="space-y-2">
                                <Textarea
                                  value={draft.allowedValuesText}
                                  onChange={event =>
                                    updateDraft(column, {
                                      allowedValuesText: event.target.value,
                                    })
                                  }
                                  placeholder="逗号分隔，如 A, B, C"
                                  className="min-h-[72px] resize-none rounded-2xl bg-zinc-50/70 py-2 text-xs"
                                />
                                <div className="text-[10px] leading-relaxed text-muted-foreground">
                                  生效值：{effectiveRangeText || "无"}
                                </div>
                                <div className="text-[10px] leading-relaxed text-muted-foreground">
                                  采集值：{harvestedRangeText || "无"}
                                </div>
                              </div>
                            </TableCell>
                            <TableCell>
                              <div className="space-y-2">
                                <Textarea
                                  value={draft.businessDescription}
                                  onChange={event =>
                                    updateDraft(column, {
                                      businessDescription: event.target.value,
                                    })
                                  }
                                  placeholder="补充业务定义、口径约束、使用建议"
                                  className="min-h-[96px] resize-none rounded-2xl bg-zinc-50/70 py-2 text-xs"
                                />
                                <div className="text-[10px] leading-relaxed text-muted-foreground">
                                  该字段为人工补充层，不会被重新采集覆盖。
                                </div>
                              </div>
                            </TableCell>
                          </TableRow>
                        )
                      })
                    )}
                  </TableBody>
                </Table>
              </div>

              {selectedTable.table_ddl ? (
                <div className="mt-6 rounded-[2rem] border bg-card p-6 shadow-sm">
                  <div className="mb-3 text-[10px] font-black uppercase tracking-widest text-muted-foreground">
                    Table DDL
                  </div>
                  <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-2xl bg-zinc-50 p-4 font-mono text-xs leading-relaxed dark:bg-zinc-900">
                    {selectedTable.table_ddl}
                  </pre>
                </div>
              ) : null}
            </div>
          </>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 text-muted-foreground">
            <Search className="h-12 w-12 opacity-10" />
            <p className="text-xs font-black uppercase tracking-widest opacity-30">
              当前筛选条件下没有可展示的表
            </p>
          </div>
        )}
      </section>
    </div>
  )
}
