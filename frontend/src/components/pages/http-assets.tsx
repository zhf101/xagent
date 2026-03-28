"use client"

import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { Bug, Eye, Pencil, Plus, RefreshCw, Target, Trash2 } from "lucide-react"

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
import { cn, getApiUrl } from "@/lib/utils"
import { apiRequest } from "@/lib/api-wrapper"

interface BizSystemRecord {
  id: number
  system_short: string
  system_name: string
}

interface HttpAssetRecord {
  id: number
  name: string
  asset_type: string
  system_short: string
  status: string
  description?: string | null
  config: Record<string, any>
  sensitivity_level?: string | null
  version: number
}

interface HttpAssetFormState {
  name: string
  system_short: string
  description: string
  sensitivity_level: string
  base_url: string
  path_template: string
  method: string
  auth_type: string
  auth_token: string
  api_key_param: string
  timeout: string
  retry_count: string
  default_headers_json: string
  query_params_json: string
  json_body_json: string
  form_fields_json: string
  response_extract_json: string
}

interface ResolveFormState {
    system_short: string
    method: string
    url: string
}

interface HttpResolveResult {
  matched: boolean
  asset_id?: number | null
  asset_name?: string | null
  reason?: string | null
  recall_strategy?: string | null
  used_ann?: boolean
  used_fallback?: boolean
  score_breakdown?: Record<string, number>
  stage_results?: Array<{
    stage_name: string
    strategy: string
    candidate_count: number
    fallback_reason?: string | null
  }>
  fallback_candidates?: Array<{
    asset_id?: number
    asset_name?: string
    description?: string
    path_template?: string
    method?: string
    match_score?: number
    score_breakdown?: Record<string, number>
  }>
}

interface HttpAssetDebugResult {
  success: boolean
  status_code: number
  body: any
  extracted_fields: Record<string, any>
  summary?: string | null
  asset_match: {
    matched: boolean
    asset_id?: number | null
    asset_name?: string | null
    reason?: string | null
  }
  downloaded_file_id?: string | null
  downloaded_file_path?: string | null
  error?: string | null
}

const EMPTY_FORM: HttpAssetFormState = {
  name: "",
  system_short: "",
  description: "",
  sensitivity_level: "",
  base_url: "",
  path_template: "",
  method: "POST",
  auth_type: "",
  auth_token: "",
  api_key_param: "api_key",
  timeout: "30",
  retry_count: "1",
  default_headers_json: "{}",
  query_params_json: "{}",
  json_body_json: "",
  form_fields_json: "{}",
  response_extract_json: "{}",
}

const EMPTY_RESOLVE_FORM: ResolveFormState = {
  system_short: "",
  method: "POST",
  url: "",
}

function parseJsonField(label: string, value: string, fallback: any) {
  if (!value.trim()) return fallback
  try {
    return JSON.parse(value)
  } catch {
    throw new Error(`${label} 不是合法 JSON`)
  }
}

function methodBadgeTone(method: string) {
  if (method === "GET") return "border-blue-500/30 bg-blue-500/10 text-blue-600"
  if (method === "POST") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-600"
  return "border-border bg-white text-muted-foreground"
}

export function HttpAssetsPage() {
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [resolving, setResolving] = useState(false)
  const [assets, setAssets] = useState<HttpAssetRecord[]>([])
  const [systems, setSystems] = useState<BizSystemRecord[]>([])
  const [search, setSearch] = useState("")
  const [selectedSystemFilter, setSelectedSystemFilter] = useState("all")
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false)
  const [isResolveDialogOpen, setIsResolveDialogOpen] = useState(false)
  const [isDebugDialogOpen, setIsDebugDialogOpen] = useState(false)
  const [editingAsset, setEditingAsset] = useState<HttpAssetRecord | null>(null)
  const [viewingAsset, setViewingAsset] = useState<HttpAssetRecord | null>(null)
  const [form, setForm] = useState<HttpAssetFormState>(EMPTY_FORM)
  const [resolveForm, setResolveForm] = useState<ResolveFormState>(EMPTY_RESOLVE_FORM)
  const [resolveResult, setResolveResult] = useState<HttpResolveResult | null>(null)
  const [debuggingAsset, setDebuggingAsset] = useState<HttpAssetRecord | null>(null)
  const [debugSubmitting, setDebugSubmitting] = useState(false)
  const [debugResult, setDebugResult] = useState<HttpAssetDebugResult | null>(null)
  const [currentStep, setCurrentStep] = useState(1)
  const [debugForm, setDebugForm] = useState({
    system_short: "",
    method: "GET",
    url: "",
    query_params_json: "{}",
    json_body_json: "",
    form_fields_json: "{}",
    headers_json: "{}",
    response_extract_json: "{}",
  })

  const loadAll = async () => {
    setLoading(true)
    try {
      const [assetRes, systemRes] = await Promise.all([
        apiRequest(`${getApiUrl()}/api/datamakepool/http-assets`, { headers: {} }),
        apiRequest(`${getApiUrl()}/api/text2sql/systems`, { headers: {} }),
      ])

      if (!assetRes.ok || !systemRes.ok) {
        const detail = await assetRes.json().catch(() => ({}))
        throw new Error(detail.detail || "加载 HTTP 资产失败")
      }

      const [assetPayload, systemPayload] = await Promise.all([
        assetRes.json(),
        systemRes.json(),
      ])
      setAssets(assetPayload)
      setSystems(systemPayload)
      setForm((prev) => ({
        ...prev,
        system_short: prev.system_short || systemPayload[0]?.system_short || "",
      }))
      setResolveForm((prev) => ({
        ...prev,
        system_short: prev.system_short || systemPayload[0]?.system_short || "",
      }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载 HTTP 资产失败")
      setAssets([])
      setSystems([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadAll()
  }, [])

  const filteredAssets = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    return assets.filter((item) =>
      (selectedSystemFilter === "all" || item.system_short === selectedSystemFilter) &&
      (!keyword ||
        [
          item.name,
          item.system_short,
          item.config?.base_url || "",
          item.config?.path_template || "",
        ].some((field) => String(field).toLowerCase().includes(keyword)))
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

  const methodOptions: SelectOption[] = [
    { value: "GET", label: "GET" },
    { value: "POST", label: "POST" },
    { value: "PUT", label: "PUT" },
    { value: "PATCH", label: "PATCH" },
    { value: "DELETE", label: "DELETE" },
  ]

  const authOptions: SelectOption[] = [
    { value: "", label: "无鉴权" },
    { value: "bearer", label: "Bearer" },
    { value: "basic", label: "Basic" },
    { value: "api_key", label: "API Key Header" },
    { value: "api_key_query", label: "API Key Query" },
  ]

  const openCreateDialog = () => {
    setEditingAsset(null)
    setCurrentStep(1)
    setForm({
      ...EMPTY_FORM,
      system_short: systems[0]?.system_short || "",
    })
    setIsCreateDialogOpen(true)
  }

  const openEditDialog = (asset: HttpAssetRecord) => {
    setEditingAsset(asset)
    setCurrentStep(1)
    setForm({
      name: asset.name,
      system_short: asset.system_short,
      description: asset.description || "",
      sensitivity_level: asset.sensitivity_level || "",
      base_url: String(asset.config?.base_url || ""),
      path_template: String(asset.config?.path_template || ""),
      method: String(asset.config?.method || "POST"),
      auth_type: String(asset.config?.auth_type || ""),
      auth_token: String(asset.config?.auth_token || ""),
      api_key_param: String(asset.config?.api_key_param || "api_key"),
      timeout: String(asset.config?.timeout ?? 30),
      retry_count: String(asset.config?.retry_count ?? 1),
      default_headers_json: JSON.stringify(asset.config?.default_headers || {}, null, 2),
      query_params_json: JSON.stringify(asset.config?.query_params || {}, null, 2),
      json_body_json: asset.config?.json_body ? JSON.stringify(asset.config.json_body, null, 2) : "",
      form_fields_json: JSON.stringify(asset.config?.form_fields || {}, null, 2),
      response_extract_json: JSON.stringify(asset.config?.response_extract || {}, null, 2),
    })
    setIsCreateDialogOpen(true)
  }

  const openDebugDialog = (asset: HttpAssetRecord) => {
    setDebuggingAsset(asset)
    setDebugResult(null)
    setDebugForm({
      system_short: asset.system_short,
      method: String(asset.config?.method || "GET"),
      url: `${String(asset.config?.base_url || "").replace(/\/$/, "")}${String(asset.config?.path_template || "")}`,
      query_params_json: JSON.stringify(asset.config?.query_params || {}, null, 2),
      json_body_json: asset.config?.json_body ? JSON.stringify(asset.config.json_body, null, 2) : "",
      form_fields_json: JSON.stringify(asset.config?.form_fields || {}, null, 2),
      headers_json: JSON.stringify(asset.config?.default_headers || {}, null, 2),
      response_extract_json: JSON.stringify(asset.config?.response_extract || {}, null, 2),
    })
    setIsDebugDialogOpen(true)
  }

  const handleCreate = async () => {
    if (!form.name.trim() || !form.system_short.trim() || !form.base_url.trim() || !form.path_template.trim()) {
      toast.error("请填写名称、系统、base_url 和 path_template")
      return
    }

    let default_headers: Record<string, any> = {}
    let query_params: Record<string, any> = {}
    let json_body: Record<string, any> | any[] | null = null
    let form_fields: Record<string, any> = {}
    let response_extract: Record<string, any> = {}
    try {
      default_headers = parseJsonField("默认请求头", form.default_headers_json, {})
      query_params = parseJsonField("默认查询参数", form.query_params_json, {})
      form_fields = parseJsonField("默认表单字段", form.form_fields_json, {})
      response_extract = parseJsonField("响应提取规则", form.response_extract_json, {})
      json_body = form.json_body_json.trim()
        ? parseJsonField("默认 JSON Body", form.json_body_json, null)
        : null
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "JSON 解析失败")
      return
    }

    setSubmitting(true)
    try {
      const url = editingAsset
        ? `${getApiUrl()}/api/datamakepool/http-assets/${editingAsset.id}`
        : `${getApiUrl()}/api/datamakepool/http-assets`
      const response = await apiRequest(url, {
        method: editingAsset ? "PUT" : "POST",
        headers: {},
        body: JSON.stringify({
          name: form.name,
          system_short: form.system_short,
          description: form.description || null,
          sensitivity_level: form.sensitivity_level || null,
          config: {
            base_url: form.base_url,
            path_template: form.path_template,
            method: form.method,
            default_headers,
            query_params,
            json_body,
            form_fields,
            auth_type: form.auth_type || null,
            auth_token: form.auth_token || null,
            api_key_param: form.api_key_param || "api_key",
            timeout: Number(form.timeout || "30"),
            retry_count: Number(form.retry_count || "1"),
            allow_redirects: true,
            response_extract,
          },
        }),
      })

      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || (editingAsset ? "更新 HTTP 资产失败" : "创建 HTTP 资产失败"))
      }
      setIsCreateDialogOpen(false)
      setEditingAsset(null)
      setForm(EMPTY_FORM)
      await loadAll()
      toast.success(editingAsset ? "HTTP 资产已更新" : "HTTP 资产已创建")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : (editingAsset ? "更新 HTTP 资产失败" : "创建 HTTP 资产失败"))
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (asset: HttpAssetRecord) => {
    if (!confirm(`确定要删除 HTTP 资产“${asset.name}”吗？`)) return
    try {
      const response = await apiRequest(
        `${getApiUrl()}/api/datamakepool/http-assets/${asset.id}`,
        { method: "DELETE", headers: {} },
      )
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || "删除 HTTP 资产失败")
      }
      if (viewingAsset?.id === asset.id) {
        setViewingAsset(null)
      }
      await loadAll()
      toast.success("HTTP 资产已删除")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除 HTTP 资产失败")
    }
  }

  const handleResolve = async () => {
    if (!resolveForm.url.trim()) {
      toast.error("请输入要测试命中的 URL")
      return
    }
    setResolving(true)
    try {
      const response = await apiRequest(`${getApiUrl()}/api/datamakepool/http-assets/resolve`, {
        method: "POST",
        headers: {},
        body: JSON.stringify(resolveForm),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || "HTTP 资产命中测试失败")
      }
      setResolveResult(payload)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "HTTP 资产命中测试失败")
      setResolveResult(null)
    } finally {
      setResolving(false)
    }
  }

  const handleDebug = async () => {
    if (!debuggingAsset) return
    if (!debugForm.url.trim()) {
      toast.error("请输入调试 URL")
      return
    }

    let query_params = {}
    let json_body: Record<string, any> | any[] | null = null
    let form_fields = {}
    let headers = {}
    let response_extract = {}
    try {
      query_params = parseJsonField("调试 Query", debugForm.query_params_json, {})
      form_fields = parseJsonField("调试 Form", debugForm.form_fields_json, {})
      headers = parseJsonField("调试 Headers", debugForm.headers_json, {})
      response_extract = parseJsonField("响应提取规则", debugForm.response_extract_json, {})
      json_body = debugForm.json_body_json.trim()
        ? parseJsonField("调试 JSON Body", debugForm.json_body_json, null)
        : null
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "调试参数 JSON 解析失败")
      return
    }

    setDebugSubmitting(true)
    try {
      const response = await apiRequest(
        `${getApiUrl()}/api/datamakepool/http-assets/${debuggingAsset.id}/debug`,
        {
          method: "POST",
          headers: {},
          body: JSON.stringify({
            system_short: debugForm.system_short || null,
            method: debugForm.method,
            url: debugForm.url,
            query_params,
            json_body,
            form_fields,
            headers,
            response_extract,
          }),
        },
      )
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || "HTTP 资产调试失败")
      }
      setDebugResult(payload)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "HTTP 资产调试失败")
      setDebugResult(null)
    } finally {
      setDebugSubmitting(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="border-b border-border/80 px-6 py-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg border border-border bg-primary/5 px-2.5 py-1 text-xs font-medium text-primary">
              HTTP ASSET
            </div>
            <h1 className="text-xl font-semibold tracking-tight">HTTP 资产</h1>
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
              新增 HTTP 资产
            </Button>
          </div>
        </div>
      </div>

      <div className="p-6">
        <Card className="overflow-hidden border-border/80 py-0 shadow-none">
          <CardHeader className="gap-3 border-b border-border/80 py-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center gap-2">
                <CardTitle className="text-base">HTTP 资产列表</CardTitle>
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
                    placeholder="搜索 HTTP 资产..."
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
                    <TableHead>方法</TableHead>
                    <TableHead>路径</TableHead>
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
                        暂无 HTTP 资产
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredAssets.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="py-3">
                          <div className="font-medium">{item.name}</div>
                          <div className="max-w-[280px] truncate text-[11px] text-muted-foreground">
                            {item.config?.base_url || "-"}
                          </div>
                        </TableCell>
                        <TableCell className="py-3">
                          <div>{item.system_short}</div>
                        </TableCell>
                        <TableCell className="py-3">
                          <Badge variant="outline" className={methodBadgeTone(String(item.config?.method || "GET"))}>
                            {String(item.config?.method || "GET")}
                          </Badge>
                        </TableCell>
                        <TableCell className="py-3 text-sm">
                          {String(item.config?.path_template || "-")}
                        </TableCell>
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
                                <Button size="sm" variant="outline" className="h-8 rounded-md px-2.5" onClick={() => openDebugDialog(item)}>
                                  <Bug className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>调试预览</TooltipContent>
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

      <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-hidden p-0">
          <div className="flex max-h-[90vh] flex-col">
            <div className="border-b border-border/70 px-6 py-5">
              <DialogHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <DialogTitle>{editingAsset ? "编辑 HTTP 资产" : "新增 HTTP 资产"}</DialogTitle>
                    <DialogDescription className="mt-1">
                      {currentStep === 1 && "第一步：基本连接信息"}
                      {currentStep === 2 && "第二步：鉴权与参数配置"}
                      {currentStep === 3 && "第三步：请求体与响应提取"}
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
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">资产名称</Label>
                      <Input value={form.name} onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))} placeholder="例如：获取订单详情" />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">所属系统</Label>
                      <Select
                        value={form.system_short}
                        onValueChange={(value) => setForm((prev) => ({ ...prev, system_short: value }))}
                        options={systemOptions}
                        placeholder="选择所属系统"
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm font-semibold">Base URL</Label>
                    <Input value={form.base_url} onChange={(e) => setForm((prev) => ({ ...prev, base_url: e.target.value }))} placeholder="https://api.example.com" />
                  </div>
                  <div className="grid grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">请求方法</Label>
                      <Select
                        value={form.method}
                        onValueChange={(value) => setForm((prev) => ({ ...prev, method: value }))}
                        options={methodOptions}
                      />
                    </div>
                    <div className="col-span-2 space-y-2">
                      <Label className="text-sm font-semibold">Path Template</Label>
                      <Input value={form.path_template} onChange={(e) => setForm((prev) => ({ ...prev, path_template: e.target.value }))} placeholder="/v1/orders/{order_id}" />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm font-semibold">接口描述</Label>
                    <Textarea rows={3} value={form.description} onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))} placeholder="详细描述该接口的功能和用途" />
                  </div>
                </div>
              )}

              {currentStep === 2 && (
                <div className="space-y-5 animate-in fade-in slide-in-from-right-4 duration-300">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">鉴权类型</Label>
                      <Select
                        value={form.auth_type}
                        onValueChange={(value) => setForm((prev) => ({ ...prev, auth_type: value }))}
                        options={authOptions}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">鉴权 Token / Key</Label>
                      <Input value={form.auth_token} onChange={(e) => setForm((prev) => ({ ...prev, auth_token: e.target.value }))} placeholder="Token 或 API Key" />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">默认请求头 (JSON)</Label>
                      <Textarea rows={4} className="font-mono text-xs" value={form.default_headers_json} onChange={(e) => setForm((prev) => ({ ...prev, default_headers_json: e.target.value }))} />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">查询参数 (JSON)</Label>
                      <Textarea rows={4} className="font-mono text-xs" value={form.query_params_json} onChange={(e) => setForm((prev) => ({ ...prev, query_params_json: e.target.value }))} />
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">超时时间 (s)</Label>
                      <Input type="number" value={form.timeout} onChange={(e) => setForm((prev) => ({ ...prev, timeout: e.target.value }))} />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">重试次数</Label>
                      <Input type="number" value={form.retry_count} onChange={(e) => setForm((prev) => ({ ...prev, retry_count: e.target.value }))} />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">敏感等级</Label>
                      <Input value={form.sensitivity_level} onChange={(e) => setForm((prev) => ({ ...prev, sensitivity_level: e.target.value }))} placeholder="L1 / L2" />
                    </div>
                  </div>
                </div>
              )}

              {currentStep === 3 && (
                <div className="space-y-5 animate-in fade-in slide-in-from-right-4 duration-300">
                  <div className="space-y-2">
                    <Label className="text-sm font-semibold">JSON 请求体 (JSON)</Label>
                    <Textarea rows={5} className="font-mono text-xs" value={form.json_body_json} onChange={(e) => setForm((prev) => ({ ...prev, json_body_json: e.target.value }))} placeholder='{"key": "value"}' />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm font-semibold">表单字段 (JSON)</Label>
                    <Textarea rows={3} className="font-mono text-xs" value={form.form_fields_json} onChange={(e) => setForm((prev) => ({ ...prev, form_fields_json: e.target.value }))} />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm font-semibold">响应提取规则 (JSON)</Label>
                    <Textarea rows={5} className="font-mono text-xs" value={form.response_extract_json} onChange={(e) => setForm((prev) => ({ ...prev, response_extract_json: e.target.value }))} />
                    <p className="text-[11px] text-muted-foreground">定义如何从 API 响应中提取字段供后续节点使用。</p>
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
                  <Button variant="ghost" onClick={() => setIsCreateDialogOpen(false)}>
                    取消
                  </Button>
                  {currentStep < 3 ? (
                    <Button 
                      onClick={() => setCurrentStep(prev => prev + 1)}
                      disabled={currentStep === 1 && (!form.name.trim() || !form.base_url.trim() || !form.path_template.trim())}
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
            <DialogTitle>查看 HTTP 资产</DialogTitle>
            <DialogDescription>查看 HTTP 资产的请求模板和默认配置。</DialogDescription>
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
                <div className="text-xs text-muted-foreground">描述</div>
                <div className="mt-1 text-sm">{viewingAsset.description || "-"}</div>
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

      <Dialog open={isDebugDialogOpen} onOpenChange={setIsDebugDialogOpen}>
        <DialogContent className="max-h-[90vh] max-w-4xl overflow-hidden p-0">
          <div className="flex max-h-[90vh] flex-col">
            <div className="border-b border-border/70 px-6 py-5">
              <DialogHeader>
                <DialogTitle>HTTP 资产调试面板</DialogTitle>
                <DialogDescription>预览原始响应、提取字段和摘要结果，不写正式运行账本。</DialogDescription>
              </DialogHeader>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-5">
              <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>所属系统</Label>
                  <Select
                    value={debugForm.system_short}
                    onValueChange={(value) => setDebugForm((prev) => ({ ...prev, system_short: value }))}
                    options={systemOptions}
                    placeholder="请选择所属系统"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Method</Label>
                  <Select
                    value={debugForm.method}
                    onValueChange={(value) => setDebugForm((prev) => ({ ...prev, method: value }))}
                    options={methodOptions}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label>URL</Label>
                <Input value={debugForm.url} onChange={(e) => setDebugForm((prev) => ({ ...prev, url: e.target.value }))} />
              </div>
              <div className="space-y-2">
                <Label>Headers JSON</Label>
                <Textarea rows={4} value={debugForm.headers_json} onChange={(e) => setDebugForm((prev) => ({ ...prev, headers_json: e.target.value }))} />
              </div>
              <div className="space-y-2">
                <Label>Query JSON</Label>
                <Textarea rows={4} value={debugForm.query_params_json} onChange={(e) => setDebugForm((prev) => ({ ...prev, query_params_json: e.target.value }))} />
              </div>
              <div className="space-y-2">
                <Label>JSON Body</Label>
                <Textarea rows={4} value={debugForm.json_body_json} onChange={(e) => setDebugForm((prev) => ({ ...prev, json_body_json: e.target.value }))} />
              </div>
              <div className="space-y-2">
                <Label>Form JSON</Label>
                <Textarea rows={4} value={debugForm.form_fields_json} onChange={(e) => setDebugForm((prev) => ({ ...prev, form_fields_json: e.target.value }))} />
              </div>
              <div className="space-y-2">
                <Label>响应提取规则 JSON</Label>
                <Textarea rows={6} value={debugForm.response_extract_json} onChange={(e) => setDebugForm((prev) => ({ ...prev, response_extract_json: e.target.value }))} />
              </div>
            </div>
            <div className="space-y-4">
              <div className="rounded-xl border border-border bg-white p-4">
                <div className="text-xs text-muted-foreground">命中结果</div>
                <pre className="mt-2 whitespace-pre-wrap break-all text-xs">
                  {JSON.stringify(debugResult?.asset_match || null, null, 2)}
                </pre>
              </div>
              <div className="rounded-xl border border-border bg-white p-4">
                <div className="text-xs text-muted-foreground">摘要</div>
                <div className="mt-2 text-sm">{debugResult?.summary || "-"}</div>
              </div>
              <div className="rounded-xl border border-border bg-white p-4">
                <div className="text-xs text-muted-foreground">提取字段</div>
                <pre className="mt-2 whitespace-pre-wrap break-all text-xs">
                  {JSON.stringify(debugResult?.extracted_fields || null, null, 2)}
                </pre>
              </div>
              <div className="rounded-xl border border-border bg-white p-4">
                <div className="text-xs text-muted-foreground">原始响应</div>
                <pre className="mt-2 max-h-[260px] overflow-auto whitespace-pre-wrap break-all text-xs">
                  {JSON.stringify(debugResult?.body || null, null, 2)}
                </pre>
              </div>
            </div>
              </div>
            </div>
            <div className="border-t border-border/70 px-6 py-4">
              <DialogFooter>
                <Button variant="outline" onClick={() => setIsDebugDialogOpen(false)}>
                  关闭
                </Button>
                <Button onClick={handleDebug} disabled={debugSubmitting}>
                  {debugSubmitting ? "调试中..." : "执行预览"}
                </Button>
              </DialogFooter>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={isResolveDialogOpen} onOpenChange={setIsResolveDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>HTTP 资产命中测试</DialogTitle>
            <DialogDescription>输入系统、方法和 URL，验证是否能命中已治理的 HTTP 资产。</DialogDescription>
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
              <Label>Method</Label>
              <Select
                value={resolveForm.method}
                onValueChange={(value) => setResolveForm((prev) => ({ ...prev, method: value }))}
                options={methodOptions}
              />
            </div>
            <div className="space-y-2">
              <Label>URL</Label>
              <Input
                value={resolveForm.url}
                onChange={(e) => setResolveForm((prev) => ({ ...prev, url: e.target.value }))}
                placeholder="https://example.com/api/users"
              />
            </div>
            {resolveResult ? (
              <div className="rounded-xl border border-border bg-white p-4 text-sm">
                <div className="font-medium">{resolveResult.matched ? "命中成功" : "未命中"}</div>
                <div className="mt-2 text-muted-foreground">
                  {resolveResult.asset_name ? `资产：${resolveResult.asset_name}` : resolveResult.reason || "-"}
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
                {resolveResult.fallback_candidates && resolveResult.fallback_candidates.length > 0 ? (
                  <div className="mt-3 space-y-2 rounded-lg border border-border/70 bg-background/70 p-3">
                    <div className="text-xs font-medium text-foreground">候选列表</div>
                    {resolveResult.fallback_candidates.map((candidate, index) => (
                      <div key={`${candidate.asset_id || index}-${candidate.asset_name || "candidate"}`} className="rounded-md border border-border/70 px-3 py-2 text-xs">
                        <div className="font-medium text-foreground">
                          {index + 1}. {candidate.asset_name || "未命名资产"}
                        </div>
                        <div className="mt-1 text-muted-foreground">
                          {candidate.method || "-"} {candidate.path_template || "-"}
                          {candidate.match_score != null ? ` · 分数：${candidate.match_score}` : ""}
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
