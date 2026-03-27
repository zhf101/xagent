"use client"

import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { Eye, Pencil, Plus, RefreshCw, Target, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
import { getApiUrl } from "@/lib/utils"
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
  const [resolveResult, setResolveResult] = useState<any>(null)

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
        system_short: prev.system_short || systemPayload[0]?.system_short || "",
        datasource_asset_id:
          prev.datasource_asset_id || String(datasourcePayload[0]?.id || ""),
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
    return datasources
      .filter(
        (item) =>
          !form.system_short || item.system_short === form.system_short
      )
      .map((item) => ({
        value: String(item.id),
        label: item.name,
        description: item.system_short,
      }))
  }, [datasources, form.system_short])

  const sqlKindOptions: SelectOption[] = [
    { value: "select", label: "SELECT" },
    { value: "insert", label: "INSERT" },
    { value: "update", label: "UPDATE" },
    { value: "delete", label: "DELETE" },
    { value: "ddl", label: "DDL" },
  ]

  const openCreateDialog = () => {
    setEditingAsset(null)
    setForm({
      ...EMPTY_FORM,
      system_short: systems[0]?.system_short || "",
      datasource_asset_id: String(datasources[0]?.id || ""),
    })
    setIsFormDialogOpen(true)
  }

  const openEditDialog = (asset: SqlAssetRecord) => {
    setEditingAsset(asset)
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
      !form.system_short.trim() ||
      !form.datasource_asset_id.trim()
    ) {
      toast.error("请填写名称、系统和 datasource 资产")
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
          system_short: form.system_short,
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
            <div className="rounded-lg border border-border bg-muted/40 px-2.5 py-1 text-xs font-medium text-muted-foreground">
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
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{editingAsset ? "编辑 SQL 资产" : "新增 SQL 资产"}</DialogTitle>
            <DialogDescription>录入 SQL 元数据，让 SQL agent 后续优先命中已治理资产。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>资产名称</Label>
                <Input value={form.name} onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))} />
              </div>
              <div className="space-y-2">
                <Label>所属系统</Label>
                <Select
                  value={form.system_short}
                  onValueChange={(value) =>
                    setForm((prev) => ({
                      ...prev,
                      system_short: value,
                      datasource_asset_id:
                        String(
                          datasources.find((item) => item.system_short === value)?.id || ""
                        ),
                    }))
                  }
                  options={systemOptions}
                  placeholder="请选择所属系统"
                />
              </div>
              <div className="space-y-2">
                <Label>数据源资产</Label>
                <Select
                  value={form.datasource_asset_id}
                  onValueChange={(value) => setForm((prev) => ({ ...prev, datasource_asset_id: value }))}
                  options={datasourceOptions}
                  placeholder="请选择 datasource 资产"
                />
              </div>
              <div className="space-y-2">
                <Label>SQL 类型</Label>
                <Select
                  value={form.sql_kind}
                  onValueChange={(value) => setForm((prev) => ({ ...prev, sql_kind: value }))}
                  options={sqlKindOptions}
                />
              </div>
              <div className="space-y-2">
                <Label>描述</Label>
                <Input value={form.description} onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))} />
              </div>
              <div className="space-y-2">
                <Label>敏感等级</Label>
                <Input value={form.sensitivity_level} onChange={(e) => setForm((prev) => ({ ...prev, sensitivity_level: e.target.value }))} placeholder="low / medium / high" />
              </div>
            </div>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>表名（逗号分隔）</Label>
                <Input value={form.table_names} onChange={(e) => setForm((prev) => ({ ...prev, table_names: e.target.value }))} placeholder="crm_user, crm_profile" />
              </div>
              <div className="space-y-2">
                <Label>标签（逗号分隔）</Label>
                <Input value={form.tags} onChange={(e) => setForm((prev) => ({ ...prev, tags: e.target.value }))} placeholder="用户, 查询, 用户画像" />
              </div>
              <div className="space-y-2">
                <Label>审批策略</Label>
                <Input value={form.approval_policy} onChange={(e) => setForm((prev) => ({ ...prev, approval_policy: e.target.value }))} placeholder="none / requester_confirm / system_admin_confirm" />
              </div>
              <div className="space-y-2">
                <Label>风险等级</Label>
                <Input value={form.risk_level} onChange={(e) => setForm((prev) => ({ ...prev, risk_level: e.target.value }))} placeholder="low / medium / high / critical" />
              </div>
              <div className="space-y-2">
                <Label>参数 Schema JSON</Label>
                <Textarea rows={5} value={form.parameter_schema_json} onChange={(e) => setForm((prev) => ({ ...prev, parameter_schema_json: e.target.value }))} />
              </div>
              <div className="space-y-2">
                <Label>SQL Template</Label>
                <Textarea rows={7} value={form.sql_template} onChange={(e) => setForm((prev) => ({ ...prev, sql_template: e.target.value }))} placeholder="select * from crm_user where user_id = :user_id" />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsFormDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={handleCreate} disabled={submitting || datasourceOptions.length === 0}>
              {submitting ? "保存中..." : "保存"}
            </Button>
          </DialogFooter>
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
                <div className="rounded-xl border border-border bg-muted/40 p-4">
                  <div className="text-xs text-muted-foreground">资产名称</div>
                  <div className="mt-1 font-medium">{viewingAsset.name}</div>
                </div>
                <div className="rounded-xl border border-border bg-muted/40 p-4">
                  <div className="text-xs text-muted-foreground">所属系统</div>
                  <div className="mt-1 font-medium">{viewingAsset.system_short}</div>
                </div>
              </div>
              <div className="rounded-xl border border-border bg-muted/40 p-4">
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
            <DialogTitle>SQL 资产命中测试</DialogTitle>
            <DialogDescription>输入系统和任务描述，验证是否能命中已治理 SQL 资产。</DialogDescription>
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
              <div className="rounded-xl border border-border bg-muted/40 p-4 text-sm">
                <div className="font-medium">{resolveResult.matched ? "命中成功" : "未命中"}</div>
                <div className="mt-2 text-muted-foreground">
                  {resolveResult.asset_name ? `资产：${resolveResult.asset_name}` : resolveResult.reason || "-"}
                </div>
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
