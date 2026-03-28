"use client"

import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { Eye, Pencil, Plus, RefreshCw, Target, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Select, type SelectOption } from "@/components/ui/select"
import { SearchInput } from "@/components/ui/search-input"
import { Textarea } from "@/components/ui/textarea"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn, getApiUrl } from "@/lib/utils"
import { apiRequest } from "@/lib/api-wrapper"

interface BizSystemRecord {
  id: number
  system_short: string
  system_name: string
}

interface DatasourceOption {
  id: number
  name: string
  system_short: string
  description?: string | null
  db_type?: string | null
  status?: string | null
}

interface SqlAssetRecord {
  id: number
  name: string
  asset_type: string
  system_short: string
  status: string
  description?: string | null
  datasource_asset_id?: number | null
  config: Record<string, any>
  sensitivity_level?: string | null
  version: number
}

interface SqlAssetFormState {
  name: string
  system_short: string
  datasource_asset_id: string
  description: string
  sensitivity_level: string
  sql_template: string
  sql_kind: string
  table_names: string
  tags: string
  approval_policy: string
  risk_level: string
  parameter_schema_json: string
}

interface ResolveFormState {
  system_short: string
  task: string
}

interface ResolveCandidate {
  asset_id?: number
  asset_name?: string
  score?: number
  matched_signals?: string[]
  score_breakdown?: Record<string, number>
}

interface ResolveResultState {
  matched: boolean
  asset_id?: number | null
  asset_name?: string | null
  reason?: string | null
  score?: number
  matched_signals?: string[]
  candidate_count?: number
  top_candidates?: ResolveCandidate[]
  recall_strategy?: string
  used_ann?: boolean
  used_fallback?: boolean
  score_breakdown?: Record<string, number>
  stage_results?: Array<{
    stage_name: string
    strategy: string
    candidate_count: number
    fallback_reason?: string | null
  }>
}

const EMPTY_FORM: SqlAssetFormState = {
  name: "",
  system_short: "",
  datasource_asset_id: "",
  description: "",
  sensitivity_level: "",
  sql_template: "",
  sql_kind: "select",
  table_names: "",
  tags: "",
  approval_policy: "",
  risk_level: "",
  parameter_schema_json: "{}",
}

const EMPTY_RESOLVE_FORM: ResolveFormState = {
  system_short: "",
  task: "",
}

function splitCommaValues(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
}

function parseJsonField(label: string, value: string, fallback: any) {
  if (!value.trim()) return fallback
  try {
    return JSON.parse(value)
  } catch {
    throw new Error(`${label} 不是合法 JSON`)
  }
}

export function SqlAssetsPage() {
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [resolving, setResolving] = useState(false)
  const [assets, setAssets] = useState<SqlAssetRecord[]>([])
  const [systems, setSystems] = useState<BizSystemRecord[]>([])
  const [datasources, setDatasources] = useState<DatasourceOption[]>([])
  const [search, setSearch] = useState("")
  const [selectedSystemFilter, setSelectedSystemFilter] = useState("all")
  const [isFormDialogOpen, setIsFormDialogOpen] = useState(false)
  const [isResolveDialogOpen, setIsResolveDialogOpen] = useState(false)
  const [editingAsset, setEditingAsset] = useState<SqlAssetRecord | null>(null)
  const [viewingAsset, setViewingAsset] = useState<SqlAssetRecord | null>(null)
  const [form, setForm] = useState<SqlAssetFormState>(EMPTY_FORM)
  const [resolveForm, setResolveForm] = useState<ResolveFormState>(EMPTY_RESOLVE_FORM)
  const [resolveResult, setResolveResult] = useState<ResolveResultState | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [currentStep, setCurrentStep] = useState(1)

  const loadAll = async () => {
    setLoading(true)
    try {
      const [assetRes, systemRes, datasourceRes] = await Promise.all([
        apiRequest(`${getApiUrl()}/api/datamakepool/sql-assets`, { headers: {} }),
        apiRequest(`${getApiUrl()}/api/text2sql/systems`, { headers: {} }),
        apiRequest(`${getApiUrl()}/api/datamakepool/sql-assets/datasources`, {
          headers: {},
        }),
      ])

      if (!assetRes.ok || !systemRes.ok || !datasourceRes.ok) {
        const detail = await assetRes.json().catch(() => ({}))
        throw new Error(detail.detail || "加载 SQL 资产失败")
      }

      const [assetPayload, systemPayload, datasourcePayload] = await Promise.all([
        assetRes.json(),
        systemRes.json(),
        datasourceRes.json(),
      ])

      setAssets(assetPayload)
      setSystems(systemPayload)
      setDatasources(datasourcePayload)
      setForm((prev) => ({
        ...prev,
        datasource_asset_id: prev.datasource_asset_id || String(datasourcePayload[0]?.id || ""),
        system_short:
          prev.system_short ||
          datasourcePayload[0]?.system_short ||
          systemPayload[0]?.system_short ||
          "",
      }))
      setResolveForm((prev) => ({
        ...prev,
        system_short: prev.system_short || systemPayload[0]?.system_short || "",
      }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载 SQL 资产失败")
      setAssets([])
      setSystems([])
      setDatasources([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadAll()
  }, [])

  const filteredAssets = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    return assets.filter(
      (item) =>
        (selectedSystemFilter === "all" ||
          item.system_short === selectedSystemFilter) &&
        (!keyword ||
          [
            item.name,
            item.system_short,
            item.config?.sql_kind || "",
            ...(item.config?.table_names || []),
          ].some((field) =>
            String(field).toLowerCase().includes(keyword)
          ))
    )
  }, [assets, search, selectedSystemFilter])

  const systemFilterOptions: SelectOption[] = useMemo(
    () => [
      { value: "all", label: "全部系统", description: "不过滤业务系统" },
      ...systems.map((item) => ({
        value: item.system_short,
        label: item.system_name,
        description: item.system_short,
      })),
    ],
    [systems]
  )

  const systemOptions: SelectOption[] = useMemo(
    () =>
      systems.map((item) => ({
        value: item.system_short,
        label: item.system_name,
        description: item.system_short,
      })),
    [systems]
  )

  const datasourceOptions: SelectOption[] = useMemo(() => {
    return datasources.map((item) => ({
      value: String(item.id),
      label: item.name,
      description: `${item.system_short}${item.db_type ? ` / ${item.db_type}` : ""}`,
    }))
  }, [datasources])

  const selectedDatasource = useMemo(
    () =>
      datasources.find((item) => String(item.id) === form.datasource_asset_id) ?? null,
    [datasources, form.datasource_asset_id]
  )

  const sqlKindOptions: SelectOption[] = [
    { value: "select", label: "SELECT" },
    { value: "insert", label: "INSERT" },
    { value: "update", label: "UPDATE" },
    { value: "delete", label: "DELETE" },
    { value: "ddl", label: "DDL" },
  ]

  const openCreateDialog = () => {
    setEditingAsset(null)
    setShowAdvanced(false)
    setCurrentStep(1)
    setForm({
      ...EMPTY_FORM,
      datasource_asset_id: String(datasources[0]?.id || ""),
      system_short: datasources[0]?.system_short || "",
    })
    setIsFormDialogOpen(true)
  }

  const openEditDialog = (asset: SqlAssetRecord) => {
    setEditingAsset(asset)
    setShowAdvanced(false)
    setCurrentStep(1)
    setForm({
      name: asset.name,
      system_short: asset.system_short,
      datasource_asset_id: String(asset.datasource_asset_id || ""),
      description: asset.description || "",
      sensitivity_level: asset.sensitivity_level || "",
      sql_template: String(asset.config?.sql_template || ""),
      sql_kind: String(asset.config?.sql_kind || "select"),
      table_names: (asset.config?.table_names || []).join(", "),
      tags: (asset.config?.tags || []).join(", "),
      approval_policy: String(asset.config?.approval_policy || ""),
      risk_level: String(asset.config?.risk_level || ""),
      parameter_schema_json: JSON.stringify(
        asset.config?.parameter_schema || {},
        null,
        2
      ),
    })
    setIsFormDialogOpen(true)
  }

  const handleCreate = async () => {
    if (
      !form.name.trim() ||
      !form.datasource_asset_id.trim()
    ) {
      toast.error("请先填写资产名称并选择已配置的数据源")
      return
    }
    if (!selectedDatasource?.system_short) {
      toast.error("当前数据源缺少 system_short，无法创建 SQL 资产")
      return
    }

    let parameter_schema = {}
    try {
      parameter_schema = parseJsonField(
        "参数 Schema",
        form.parameter_schema_json,
        {}
      )
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "JSON 解析失败")
      return
    }

    setSubmitting(true)
    try {
      const url = editingAsset
        ? `${getApiUrl()}/api/datamakepool/sql-assets/${editingAsset.id}`
        : `${getApiUrl()}/api/datamakepool/sql-assets`
      const response = await apiRequest(url, {
        method: editingAsset ? "PUT" : "POST",
        headers: {},
        body: JSON.stringify({
          name: form.name,
          system_short: selectedDatasource.system_short,
          datasource_asset_id: Number(form.datasource_asset_id),
          description: form.description || null,
          sensitivity_level: form.sensitivity_level || null,
          config: {
            sql_template: form.sql_template || null,
            sql_kind: form.sql_kind || null,
            table_names: splitCommaValues(form.table_names),
            tags: splitCommaValues(form.tags),
            parameter_schema,
            approval_policy: form.approval_policy || null,
            risk_level: form.risk_level || null,
          },
        }),
      })

      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(
          payload.detail || (editingAsset ? "更新 SQL 资产失败" : "创建 SQL 资产失败")
        )
      }
      setIsFormDialogOpen(false)
      setEditingAsset(null)
      setForm(EMPTY_FORM)
      await loadAll()
      toast.success(editingAsset ? "SQL 资产已更新" : "SQL 资产已创建")
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : editingAsset
            ? "更新 SQL 资产失败"
            : "创建 SQL 资产失败"
      )
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (asset: SqlAssetRecord) => {
    if (!confirm(`确定要删除 SQL 资产“${asset.name}”吗？`)) return
    try {
      const response = await apiRequest(
        `${getApiUrl()}/api/datamakepool/sql-assets/${asset.id}`,
        { method: "DELETE", headers: {} }
      )
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || "删除 SQL 资产失败")
      }
      if (viewingAsset?.id === asset.id) {
        setViewingAsset(null)
      }
      await loadAll()
      toast.success("SQL 资产已删除")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除 SQL 资产失败")
    }
  }

  const handleResolve = async () => {
    if (!resolveForm.task.trim()) {
      toast.error("请输入要测试的任务描述")
      return
    }
    setResolving(true)
    try {
      const response = await apiRequest(
        `${getApiUrl()}/api/datamakepool/sql-assets/resolve`,
        {
          method: "POST",
          headers: {},
          body: JSON.stringify(resolveForm),
        }
      )
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || "SQL 资产命中测试失败")
      }
      setResolveResult(payload)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "SQL 资产命中测试失败")
      setResolveResult(null)
    } finally {
      setResolving(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="border-b border-border/80 px-6 py-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg border border-border bg-primary/5 px-2.5 py-1 text-xs font-medium text-primary">
              SQL ASSET
            </div>
            <h1 className="text-xl font-semibold tracking-tight">SQL 资产</h1>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => void loadAll()} disabled={loading}>
              <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              刷新
            </Button>
            <Button variant="outline" onClick={() => setIsResolveDialogOpen(true)}>
              <Target className="mr-2 h-4 w-4" />
              命中测试
            </Button>
            <Button onClick={openCreateDialog}>
              <Plus className="mr-2 h-4 w-4" />
              新增 SQL 资产
            </Button>
          </div>
        </div>
      </div>

      <div className="p-6">
        <Card className="overflow-hidden border-border/80 py-0 shadow-none">
          <CardHeader className="gap-3 border-b border-border/80 py-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center gap-2">
                <CardTitle className="text-base">SQL 资产列表</CardTitle>
                <Badge variant="outline" className="h-6 rounded-md px-2 text-xs">
                  {filteredAssets.length}
                </Badge>
              </div>
              <div className="flex w-full flex-col gap-2 lg:max-w-2xl lg:flex-row lg:justify-end">
                <div className="w-full lg:w-52">
                  <Select
                    value={selectedSystemFilter}
                    onValueChange={setSelectedSystemFilter}
                    options={systemFilterOptions}
                    placeholder="按系统筛选"
                  />
                </div>
                <div className="w-full lg:max-w-xs">
                  <SearchInput
                    value={search}
                    onChange={setSearch}
                    placeholder="搜索 SQL 资产..."
                  />
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent className="px-0 py-0">
            <TooltipProvider delayDuration={180}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名称</TableHead>
                    <TableHead>系统</TableHead>
                    <TableHead>SQL 类型</TableHead>
                    <TableHead>数据源</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>版本</TableHead>
                    <TableHead className="w-[180px]">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {loading ? (
                    <TableRow>
                      <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                        加载中...
                      </TableCell>
                    </TableRow>
                  ) : filteredAssets.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                        暂无 SQL 资产
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredAssets.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="py-3">
                          <div className="font-medium">{item.name}</div>
                          <div className="max-w-[280px] truncate text-[11px] text-muted-foreground">
                            {(item.config?.table_names || []).join(", ") || "-"}
                          </div>
                        </TableCell>
                        <TableCell className="py-3">{item.system_short}</TableCell>
                        <TableCell className="py-3">
                          <Badge variant="outline">{String(item.config?.sql_kind || "-")}</Badge>
                        </TableCell>
                        <TableCell className="py-3 text-sm">{item.datasource_asset_id || "-"}</TableCell>
                        <TableCell className="py-3">
                          <Badge variant="outline">{item.status}</Badge>
                        </TableCell>
                        <TableCell className="py-3">{item.version}</TableCell>
                        <TableCell className="py-3">
                          <div className="flex items-center gap-1.5">
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button size="sm" variant="outline" className="h-8 rounded-md px-2.5" onClick={() => setViewingAsset(item)}>
                                  <Eye className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>查看详情</TooltipContent>
                            </Tooltip>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button size="sm" variant="outline" className="h-8 rounded-md px-2.5" onClick={() => openEditDialog(item)}>
                                  <Pencil className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>编辑资产</TooltipContent>
                            </Tooltip>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button size="sm" variant="outline" className="h-8 rounded-md px-2.5 text-red-600" onClick={() => handleDelete(item)}>
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>删除资产</TooltipContent>
                            </Tooltip>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </TooltipProvider>
          </CardContent>
        </Card>
      </div>

      <Dialog open={isFormDialogOpen} onOpenChange={setIsFormDialogOpen}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-hidden p-0">
          <div className="flex max-h-[90vh] flex-col">
            <div className="border-b border-border/70 px-6 py-5">
              <DialogHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <DialogTitle>{editingAsset ? "编辑 SQL 资产" : "新增 SQL 资产"}</DialogTitle>
                    <DialogDescription className="mt-1">
                      {currentStep === 1 && "第一步：基本信息"}
                      {currentStep === 2 && "第二步：SQL 配置"}
                      {currentStep === 3 && "第三步：高级治理"}
                    </DialogDescription>
                  </div>
                  <div className="flex items-center gap-2 pr-6">
                    {[1, 2, 3].map((s) => (
                      <div
                        key={s}
                        className={cn(
                          "flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold transition-all",
                          currentStep === s
                            ? "bg-primary text-primary-foreground shadow-sm shadow-primary/20"
                            : currentStep > s
                            ? "bg-primary/20 text-primary"
                            : "bg-white border border-border text-muted-foreground"
                        )}
                      >
                        {s}
                      </div>
                    ))}
                  </div>
                </div>
              </DialogHeader>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-6">
              {currentStep === 1 && (
                <div className="space-y-5 animate-in fade-in slide-in-from-right-4 duration-300">
                  <div className="space-y-2">
                    <Label className="text-sm font-semibold">选择数据源</Label>
                    <Select
                      value={form.datasource_asset_id}
                      onValueChange={(value) => {
                        const nextDatasource =
                          datasources.find((item) => String(item.id) === value) ?? null
                        setForm((prev) => ({
                          ...prev,
                          datasource_asset_id: value,
                          system_short: nextDatasource?.system_short || "",
                        }))
                      }}
                      options={datasourceOptions}
                      placeholder="请选择已配置的数据源"
                    />
                    <p className="text-[11px] text-muted-foreground leading-relaxed">
                      SQL 资产直接挂在你已配置的数据源下面，会自动继承所属系统信息。
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">所属系统</Label>
                      <Input value={selectedDatasource?.system_short || form.system_short} readOnly className="bg-primary/5 border-primary/20" />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">资产名称</Label>
                      <Input 
                        placeholder="例如：查询用户信息"
                        value={form.name} 
                        onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))} 
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm font-semibold">描述</Label>
                    <Textarea 
                      placeholder="简要说明该 SQL 资产的用途"
                      rows={3}
                      value={form.description} 
                      onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))} 
                    />
                  </div>
                </div>
              )}

              {currentStep === 2 && (
                <div className="space-y-5 animate-in fade-in slide-in-from-right-4 duration-300">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">SQL 类型</Label>
                      <Select
                        value={form.sql_kind}
                        onValueChange={(value) => setForm((prev) => ({ ...prev, sql_kind: value }))}
                        options={sqlKindOptions}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">关联表（逗号分隔）</Label>
                      <Input 
                        value={form.table_names} 
                        onChange={(e) => setForm((prev) => ({ ...prev, table_names: e.target.value }))} 
                        placeholder="crm_user, crm_profile" 
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm font-semibold">SQL Template</Label>
                    <div className="relative">
                      <Textarea 
                        rows={8} 
                        className="font-mono text-xs leading-relaxed"
                        value={form.sql_template} 
                        onChange={(e) => setForm((prev) => ({ ...prev, sql_template: e.target.value }))} 
                        placeholder="select * from crm_user where user_id = :user_id" 
                      />
                    </div>
                    <p className="text-[11px] text-muted-foreground">支持使用 :variable 形式定义参数。</p>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm font-semibold">标签（逗号分隔）</Label>
                    <Input 
                      value={form.tags} 
                      onChange={(e) => setForm((prev) => ({ ...prev, tags: e.target.value }))} 
                      placeholder="用户, 查询, 核心数据" 
                    />
                  </div>
                </div>
              )}

              {currentStep === 3 && (
                <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
                  <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/5 p-3 text-[11px] text-yellow-600 dark:text-yellow-400">
                    提示：高级治理配置仅在需要严格管控资产风险时使用。
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">审批策略</Label>
                      <Input 
                        value={form.approval_policy} 
                        onChange={(e) => setForm((prev) => ({ ...prev, approval_policy: e.target.value }))} 
                        placeholder="none / requester_confirm" 
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">风险等级</Label>
                      <Input 
                        value={form.risk_level} 
                        onChange={(e) => setForm((prev) => ({ ...prev, risk_level: e.target.value }))} 
                        placeholder="low / medium / high" 
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm font-semibold">参数 Schema JSON</Label>
                    <Textarea 
                      rows={5} 
                      className="font-mono text-xs"
                      value={form.parameter_schema_json} 
                      onChange={(e) => setForm((prev) => ({ ...prev, parameter_schema_json: e.target.value }))} 
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm font-semibold">数据敏感度</Label>
                    <Input 
                      value={form.sensitivity_level} 
                      onChange={(e) => setForm((prev) => ({ ...prev, sensitivity_level: e.target.value }))} 
                      placeholder="L1 / L2 / L3" 
                    />
                  </div>
                </div>
              )}
            </div>

            <div className="border-t border-border/70 bg-white px-6 py-4">
              <DialogFooter className="flex items-center justify-between sm:justify-between">
                <div>
                  {currentStep > 1 && (
                    <Button variant="outline" onClick={() => setCurrentStep(prev => prev - 1)}>
                      上一步
                    </Button>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button variant="ghost" onClick={() => setIsFormDialogOpen(false)}>
                    取消
                  </Button>
                  {currentStep < 3 ? (
                    <Button 
                      onClick={() => setCurrentStep(prev => prev + 1)}
                      disabled={currentStep === 1 && (!form.name.trim() || !form.datasource_asset_id.trim())}
                    >
                      下一步
                    </Button>
                  ) : (
                    <Button onClick={handleCreate} disabled={submitting}>
                      {submitting ? "保存中..." : "保存资产"}
                    </Button>
                  )}
                </div>
              </DialogFooter>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!viewingAsset} onOpenChange={(open) => !open && setViewingAsset(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>查看 SQL 资产</DialogTitle>
            <DialogDescription>查看 SQL 资产的表、参数 schema 和模板内容。</DialogDescription>
          </DialogHeader>
          {viewingAsset ? (
            <div className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-xl border border-border bg-white p-4">
                  <div className="text-xs text-muted-foreground">资产名称</div>
                  <div className="mt-1 font-medium">{viewingAsset.name}</div>
                </div>
                <div className="rounded-xl border border-border bg-white p-4">
                  <div className="text-xs text-muted-foreground">所属系统</div>
                  <div className="mt-1 font-medium">{viewingAsset.system_short}</div>
                </div>
              </div>
              <div className="rounded-xl border border-border bg-white p-4">
                <div className="text-xs text-muted-foreground">配置</div>
                <pre className="mt-2 overflow-auto whitespace-pre-wrap break-all text-xs">
                  {JSON.stringify(viewingAsset.config || {}, null, 2)}
                </pre>
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setViewingAsset(null)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={isResolveDialogOpen} onOpenChange={setIsResolveDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>SQL 资产粗匹配测试</DialogTitle>
            <DialogDescription>输入系统和任务描述，查看当前元数据匹配到的 SQL 资产候选结果。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>所属系统</Label>
              <Select
                value={resolveForm.system_short}
                onValueChange={(value) => setResolveForm((prev) => ({ ...prev, system_short: value }))}
                options={systemOptions}
                placeholder="请选择所属系统"
              />
            </div>
            <div className="space-y-2">
              <Label>任务描述</Label>
              <Textarea
                rows={5}
                value={resolveForm.task}
                onChange={(e) => setResolveForm((prev) => ({ ...prev, task: e.target.value }))}
                placeholder="例如：查询 CRM 用户表中的用户信息"
              />
            </div>
            {resolveResult ? (
              <div className="rounded-xl border border-border bg-white p-4 text-sm">
                <div className="font-medium">{resolveResult.matched ? "命中成功" : "未命中"}</div>
                <div className="mt-2 text-muted-foreground">
                  {resolveResult.asset_name ? `资产：${resolveResult.asset_name}` : resolveResult.reason || "-"}
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                  匹配分：{resolveResult.score ?? 0} · 候选数：{resolveResult.candidate_count ?? 0}
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                  召回策略：{resolveResult.recall_strategy || "-"}
                  {` · ANN：${resolveResult.used_ann ? "是" : "否"} · 兜底：${resolveResult.used_fallback ? "是" : "否"}`}
                </div>
                {resolveResult.score_breakdown && Object.keys(resolveResult.score_breakdown).length > 0 ? (
                  <div className="mt-3 space-y-2 rounded-lg border border-border/70 bg-background/70 p-3">
                    <div className="text-xs font-medium text-foreground">分值拆解</div>
                    {Object.entries(resolveResult.score_breakdown).map(([key, value]) => (
                      <div key={key} className="rounded-md border border-border/70 px-3 py-2 text-xs text-muted-foreground">
                        {key}：{value}
                      </div>
                    ))}
                  </div>
                ) : null}
                {resolveResult.matched_signals && resolveResult.matched_signals.length > 0 ? (
                  <div className="mt-2 text-xs text-muted-foreground">
                    命中信号：{resolveResult.matched_signals.join("、")}
                  </div>
                ) : null}
                {resolveResult.stage_results && resolveResult.stage_results.length > 0 ? (
                  <div className="mt-3 space-y-2 rounded-lg border border-border/70 bg-background/70 p-3">
                    <div className="text-xs font-medium text-foreground">阶段执行</div>
                    {resolveResult.stage_results.map((stage, index) => (
                      <div key={`${stage.stage_name}-${index}`} className="rounded-md border border-border/70 px-3 py-2 text-xs text-muted-foreground">
                        {stage.stage_name} · {stage.strategy} · 候选 {stage.candidate_count}
                        {stage.fallback_reason ? ` · 原因：${stage.fallback_reason}` : ""}
                      </div>
                    ))}
                  </div>
                ) : null}
                {resolveResult.top_candidates && resolveResult.top_candidates.length > 0 ? (
                  <div className="mt-3 space-y-2 rounded-lg border border-border/70 bg-background/70 p-3">
                    <div className="text-xs font-medium text-foreground">候选列表</div>
                    {resolveResult.top_candidates.map((candidate, index) => (
                      <div key={`${candidate.asset_id || index}-${candidate.asset_name || "candidate"}`} className="rounded-md border border-border/70 px-3 py-2 text-xs">
                        <div className="font-medium text-foreground">
                          {index + 1}. {candidate.asset_name || "未命名资产"}
                        </div>
                        <div className="mt-1 text-muted-foreground">
                          分数：{candidate.score ?? 0}
                          {candidate.matched_signals && candidate.matched_signals.length > 0
                            ? ` · 信号：${candidate.matched_signals.join("、")}`
                            : ""}
                        </div>
                        {candidate.score_breakdown && Object.keys(candidate.score_breakdown).length > 0 ? (
                          <div className="mt-2 text-muted-foreground">
                            {Object.entries(candidate.score_breakdown)
                              .map(([key, value]) => `${key}: ${value}`)
                              .join(" · ")}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsResolveDialogOpen(false)}>
              关闭
            </Button>
            <Button onClick={handleResolve} disabled={resolving}>
              {resolving ? "测试中..." : "开始测试"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
