"use client"

import React, { useState, useEffect } from "react"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet"
import { Dialog, DialogContent, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Select as SelectRadix, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select-radix"
import { JSONSyntaxHighlighter } from "@/components/ui/json-syntax-highlighter"
import { toast } from "sonner"
import { getApiUrl } from "@/lib/utils"
import { apiRequest } from "@/lib/api-wrapper"
import {
  getApiErrorMessage,
  getApprovalSubmissionMessage,
} from "@/lib/api-errors"
import { 
  GdpHttpAssetPayload, 
  createDefaultGdpHttpPayload, 
  GdpHttpResource,
  GdpToolContract,
  GdpExecutionProfile,
  GdpToolAnnotations
} from "./gdp-types"
import { Save, AlertCircle, Eye, ChevronRight, Tag as TagIcon, Settings2, FileCode, Server, Database, Code, ListTree } from "lucide-react"
import { SchemaTreeEditor, SchemaNode } from "./schema-tree-editor"
import { parseTreeFromSchemaAndRoutes } from "./schema-bridge"
import {
  coerceHttpAssetPayloadFromApi,
  normalizeVisualHttpAssetDraft,
  previewHttpAssetRequest,
  saveHttpAsset,
} from "./http-config-runtime"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

interface HttpConfigDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
  assetId?: number
}

interface RequestPreviewData {
  url: string
  method: string
  headers: Record<string, string>
  body?: string | null
}

const STEPS = [
  { id: "basic", title: "基础资源", desc: "资产标识与归属", icon: Database },
  { id: "model", title: "工具定义", desc: "面向模型描述", icon: FileCode },
  { id: "input", title: "入参映射", desc: "数据结构与路由", icon: Settings2 },
  { id: "output", title: "出参定义", desc: "响应结构声明", icon: TagIcon },
  { id: "execution", title: "执行与响应", desc: "网络配置与模板", icon: Server },
]

export function HttpConfigDrawer({ open, onOpenChange, onSaved, assetId }: HttpConfigDrawerProps) {
  const [payload, setPayload] = useState<GdpHttpAssetPayload>(createDefaultGdpHttpPayload())
  const [activeStep, setActiveStep] = useState("basic")
  const [isSaving, setIsSaving] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [isPreviewOpen, setIsPreviewOpen] = useState(false)
  const [isRequestPreviewOpen, setIsRequestPreviewOpen] = useState(false)
  const [requestPreviewData, setRequestPreviewData] = useState<RequestPreviewData | null>(null)
  const [isAssembling, setIsAssembling] = useState(false)

  const [inputEditMode, setInputEditMode] = useState<"visual" | "json">("visual")
  const [outputEditMode, setOutputEditMode] = useState<"visual" | "json">("visual")
  const [inputTree, setInputTree] = useState<SchemaNode[]>([])
  const [outputTree, setOutputTree] = useState<SchemaNode[]>([])
  const [rawInputJson, setRawInputJson] = useState("")
  const [rawOutputJson, setRawOutputJson] = useState("")

  useEffect(() => {
    if (open) {
      if (assetId) {
        fetchAsset(assetId)
      } else {
        const nextPayload = createDefaultGdpHttpPayload()
        setPayload(nextPayload)
        setInputTree([])
        setOutputTree([])
        setRawInputJson(JSON.stringify(nextPayload.tool_contract.input_schema_json, null, 2))
        setRawOutputJson(JSON.stringify(nextPayload.tool_contract.output_schema_json, null, 2))
        setActiveStep("basic")
      }
    }
  }, [open, assetId])

  const fetchAsset = async (id: number) => {
    setIsLoading(true)
    try {
      const res = await apiRequest(`${getApiUrl()}/api/v1/gdp/http-assets/${id}`)
      if (res.ok) {
        const data = await res.json()
        const asset = coerceHttpAssetPayloadFromApi(data.data)
        setPayload(asset)
        
        if (asset.tool_contract.input_schema_json) {
          const tree = parseTreeFromSchemaAndRoutes(
            asset.tool_contract.input_schema_json, 
            asset.execution_profile.args_position_json || {}
          )
          setInputTree(tree)
          setRawInputJson(JSON.stringify(asset.tool_contract.input_schema_json, null, 2))
        }
        if (asset.tool_contract.output_schema_json) {
          const tree = parseTreeFromSchemaAndRoutes(asset.tool_contract.output_schema_json, {})
          setOutputTree(tree)
          setRawOutputJson(JSON.stringify(asset.tool_contract.output_schema_json, null, 2))
        }
      }
    } finally {
      setIsLoading(false)
    }
  }

  const handleSave = async () => {
    setIsSaving(true)
    try {
      const res = await saveHttpAsset({
        assetId,
        payload,
        inputEditMode,
        outputEditMode,
        inputTree,
        outputTree,
        rawInputJson,
        rawOutputJson,
      })

      if (res.ok) {
        const payload = await res.json().catch(() => null)
        toast.success(
          getApprovalSubmissionMessage(
            payload,
            assetId ? "更新申请已提交，等待系统管理员审批" : "创建申请已提交，等待系统管理员审批"
          )
        )
        onSaved()
        onOpenChange(false)
      } else {
        const error = await res.json().catch(() => null)
        toast.error(getApiErrorMessage(error, "资产保存失败"))
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "资产保存失败")
    } finally {
      setIsSaving(false)
    }
  }

  const updateResource = (key: keyof GdpHttpResource, value: unknown) => setPayload(p => ({ ...p, resource: { ...p.resource, [key]: value } }))
  const updateContract = (key: keyof GdpToolContract, value: unknown) => setPayload(p => ({ ...p, tool_contract: { ...p.tool_contract, [key]: value } }))
  const updateAnnotations = (key: keyof GdpToolAnnotations, value: unknown) => setPayload(p => ({ ...p, tool_contract: { ...p.tool_contract, annotations_json: { ...p.tool_contract.annotations_json, [key]: value } } }))
  const updateProfile = (key: keyof GdpExecutionProfile, value: unknown) => setPayload(p => ({ ...p, execution_profile: { ...p.execution_profile, [key]: value } }))
  const updateAuth = (key: string, value: unknown) => setPayload(p => ({ ...p, execution_profile: { ...p.execution_profile, auth_json: { ...p.execution_profile.auth_json, [key]: value } } }))
  const annotationHints: Array<{ key: keyof GdpToolAnnotations; label: string; desc: string }> = [
    { key: "readOnlyHint", label: "只读查询", desc: "无修改操作" },
    { key: "destructiveHint", label: "高风险/破坏性", desc: "必须强确认" },
    { key: "idempotentHint", label: "幂等性接口", desc: "支持重试" },
    { key: "openWorldHint", label: "外部强时效性", desc: "不建议缓存" },
  ]
  const updateResponseTemplate = (key: string, value: unknown) =>
    setPayload(p => ({
      ...p,
      execution_profile: {
        ...p.execution_profile,
        response_template_json: {
          ...(p.execution_profile.response_template_json || {}),
          [key]: value,
        },
      },
    }))

  const handlePreviewRequest = async () => {
    setIsAssembling(true)
    try {
      const preview = await previewHttpAssetRequest({
        payload,
        inputEditMode,
        outputEditMode,
        inputTree,
        outputTree,
        rawInputJson,
        rawOutputJson,
      })
      setRequestPreviewData(preview)
      setIsRequestPreviewOpen(true)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "请求拼装失败")
    } finally {
      setIsAssembling(false)
    }
  }

  const syncVisualInputToJson = async () => {
    const normalized = await normalizeVisualHttpAssetDraft({
      payload,
      inputTree,
    })
    setPayload(prev => ({
      ...prev,
      tool_contract: {
        ...prev.tool_contract,
        input_schema_json: normalized.tool_contract.input_schema_json,
      },
      execution_profile: {
        ...prev.execution_profile,
        args_position_json: normalized.execution_profile.args_position_json,
      },
    }))
    setRawInputJson(
      JSON.stringify(normalized.tool_contract.input_schema_json, null, 2)
    )
  }

  const syncVisualOutputToJson = async () => {
    const normalized = await normalizeVisualHttpAssetDraft({
      payload,
      outputTree,
    })
    setPayload(prev => ({
      ...prev,
      tool_contract: {
        ...prev.tool_contract,
        output_schema_json: normalized.tool_contract.output_schema_json,
      },
    }))
    setRawOutputJson(
      JSON.stringify(normalized.tool_contract.output_schema_json, null, 2)
    )
  }

  const handleInputEditModeChange = async (nextMode: "visual" | "json") => {
    if (nextMode === inputEditMode) return
    if (nextMode === "json") {
      try {
        await syncVisualInputToJson()
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "入参结构同步失败")
        return
      }
    }
    setInputEditMode(nextMode)
  }

  const handleOutputEditModeChange = async (nextMode: "visual" | "json") => {
    if (nextMode === outputEditMode) return
    if (nextMode === "json") {
      try {
        await syncVisualOutputToJson()
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "出参结构同步失败")
        return
      }
    }
    setOutputEditMode(nextMode)
  }

  if (isLoading) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="right" className="w-[95vw] sm:max-w-[1200px] flex items-center justify-center bg-background"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" /></SheetContent>
      </Sheet>
    )
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[95vw] sm:max-w-[1200px] p-0 flex flex-col bg-background h-full outline-none">
        {/* Fixed Header */}
        <div className="px-6 py-4 border-b bg-background sticky top-0 z-50 flex items-center justify-between shrink-0">
          <div>
            <div className="flex items-center gap-2">
              <SheetTitle className="text-xl font-black tracking-tight">{assetId ? '编辑资产' : '新资产注册'}</SheetTitle>
              <Badge variant="outline" className="bg-primary/5 text-primary border-primary/20">{payload.resource.system_short || "GDP"}</Badge>
            </div>
            <SheetDescription className="text-xs">采用分层协议设计，适配知识召回与 MCP 工具调用</SheetDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="rounded-full px-4 h-9" onClick={() => setIsPreviewOpen(true)}>
              <Eye className="w-4 h-4 mr-2" /> 预览 Payload
            </Button>
            <Button variant="outline" size="sm" className="rounded-full px-4 h-9 text-primary hover:text-primary hover:bg-primary/5" onClick={handlePreviewRequest} disabled={isAssembling}>
              <Code className="w-4 h-4 mr-2" /> {isAssembling ? "组装中..." : "预览请求报文"}
            </Button>
            <Button onClick={handleSave} disabled={isSaving} className="rounded-full px-6 h-9 shadow-lg">
              <Save className="w-4 h-4 mr-2" />
              {isSaving ? "保存中..." : assetId ? "更新" : "提交注册"}
            </Button>
          </div>
        </div>

        {/* Main Area: Crucial flex-1 min-h-0 */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* Sidebar */}
          <div className="w-[260px] border-r bg-muted/10 flex flex-col shrink-0 overflow-y-auto">
            <div className="p-6 space-y-1">
              <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em] mb-4 opacity-50">Configuration Steps</p>
              {STEPS.map((step) => {
                const Icon = step.icon
                const isActive = activeStep === step.id
                return (
                  <button
                    key={step.id}
                    onClick={() => setActiveStep(step.id)}
                    className={cn(
                      "w-full text-left p-4 rounded-2xl transition-all flex items-start gap-4 group relative",
                      isActive ? "bg-white dark:bg-zinc-900 shadow-xl ring-1 ring-border" : "text-muted-foreground hover:bg-muted/50"
                    )}
                  >
                    <div className={cn("p-2.5 rounded-xl shrink-0 transition-all", isActive ? "bg-primary text-primary-foreground" : "bg-muted group-hover:bg-background")}>
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className="min-w-0">
                      <div className={cn("text-sm font-bold truncate leading-tight", isActive && "text-primary")}>{step.title}</div>
                      <div className="text-[10px] text-muted-foreground mt-1 line-clamp-1">{step.desc}</div>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Right Content: Crucial overflow-y-auto h-full */}
          <div className="flex-1 bg-white dark:bg-zinc-950 overflow-y-auto h-full relative">
            <div className="p-10 max-w-[850px] mx-auto min-h-full flex flex-col pb-32">
              
              {activeStep === "basic" && (
                <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <div className="space-y-2">
                    <h2 className="text-2xl font-black tracking-tight">基础资源信息</h2>
                    <p className="text-muted-foreground text-sm">定义接口在平台中的资产身份</p>
                  </div>
                  <div className="grid grid-cols-2 gap-8 p-8 border rounded-[2rem] bg-zinc-50/50 dark:bg-zinc-900/50 border-dashed">
                    <div className="space-y-2.5"><Label className="text-xs font-black uppercase tracking-wider">资源标识 (Key) *</Label><Input value={payload.resource.resource_key} onChange={e => updateResource("resource_key", e.target.value)} placeholder="crm_user_get" className="h-11 rounded-xl" /></div>
                    <div className="space-y-2.5"><Label className="text-xs font-black uppercase tracking-wider">所属系统 *</Label><Input value={payload.resource.system_short} onChange={e => updateResource("system_short", e.target.value)} placeholder="CRM" className="h-11 rounded-xl" /></div>
                    <div className="space-y-2.5">
                      <Label className="text-xs font-black uppercase tracking-wider">可见性</Label>
                      <SelectRadix value={payload.resource.visibility} onValueChange={v => updateResource("visibility", v)}>
                        <SelectTrigger className="h-11 rounded-xl bg-background"><SelectValue /></SelectTrigger>
                        <SelectContent><SelectItem value="private">私有 (Private)</SelectItem><SelectItem value="shared">共享 (Shared)</SelectItem><SelectItem value="global">全局 (Global)</SelectItem></SelectContent>
                      </SelectRadix>
                    </div>
                    <div className="space-y-2.5"><Label className="text-xs font-black uppercase tracking-wider">标签</Label><Input value={payload.resource.tags_json.join(",")} onChange={e => updateResource("tags_json", e.target.value.split(",").map(t => t.trim()).filter(Boolean))} className="h-11 rounded-xl" /></div>
                    <div className="col-span-2 space-y-2.5"><Label className="text-xs font-black uppercase tracking-wider">资源摘要</Label><Textarea value={payload.resource.summary} onChange={e => updateResource("summary", e.target.value)} className="min-h-[80px] rounded-2xl resize-none" /></div>
                  </div>
                </div>
              )}

              {activeStep === "model" && (
                <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <div className="space-y-2"><h2 className="text-2xl font-black tracking-tight">大模型语义定义</h2><p className="text-muted-foreground text-sm">定义接口如何呈现给 LLM</p></div>
                  <div className="space-y-8">
                    <div className="grid grid-cols-2 gap-6">
                      <div className="space-y-2.5"><Label className="text-xs font-black uppercase tracking-wider">Tool 协议名称 *</Label><Input value={payload.tool_contract.tool_name} onChange={e => updateContract("tool_name", e.target.value)} className="h-11 font-mono rounded-xl" /></div>
                      <div className="space-y-2.5"><Label className="text-xs font-black uppercase tracking-wider">人类友好标题</Label><Input value={payload.tool_contract.annotations_json.title || ""} onChange={e => updateAnnotations("title", e.target.value)} className="h-11 rounded-xl" /></div>
                    </div>
                    <div className="space-y-2.5"><Label className="text-xs font-black uppercase tracking-wider">功能描述 *</Label><Textarea value={payload.tool_contract.tool_description} onChange={e => updateContract("tool_description", e.target.value)} className="min-h-[120px] rounded-2xl" /></div>
                    <div className="space-y-4">
                      <Label className="text-xs font-black uppercase tracking-wider">行为提示 (Annotations)</Label>
                      <div className="grid grid-cols-2 gap-4">
                        {annotationHints.map((hint) => (
                          <div key={hint.key} className="flex items-center justify-between p-5 rounded-[1.5rem] border bg-background hover:border-primary/40 transition-all shadow-sm">
                            <div className="space-y-1"><Label className="text-sm font-bold">{hint.label}</Label><p className="text-[10px] text-muted-foreground leading-tight">{hint.desc}</p></div>
                            <Switch checked={!!payload.tool_contract.annotations_json[hint.key]} onCheckedChange={v => updateAnnotations(hint.key, v)} />
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {activeStep === "input" && (
                <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <div className="flex items-center justify-between">
                    <div className="space-y-1"><h2 className="text-2xl font-black tracking-tight">入参映射配置</h2><p className="text-muted-foreground text-sm">定义 Schema 结构与路由</p></div>
                    <div className="flex bg-muted p-1 rounded-xl">
                      <Button variant={inputEditMode === "visual" ? "secondary" : "ghost"} size="sm" className="h-8 rounded-lg text-xs gap-1.5" onClick={() => handleInputEditModeChange("visual")}><ListTree className="w-3.5 h-3.5" /> 可视化</Button>
                      <Button variant={inputEditMode === "json" ? "secondary" : "ghost"} size="sm" className="h-8 rounded-lg text-xs gap-1.5" onClick={() => handleInputEditModeChange("json")}><Code className="w-3.5 h-3.5" /> 源码</Button>
                    </div>
                  </div>
                  {inputEditMode === "visual" ? (
                    <div className="p-6 border rounded-[2rem] bg-zinc-50/30 dark:bg-white/5"><SchemaTreeEditor value={inputTree} onChange={setInputTree} enableRoute={true} method={payload.execution_profile.method} /></div>
                  ) : (
                    <Textarea value={rawInputJson} onChange={e => setRawInputJson(e.target.value)} className="min-h-[400px] font-mono text-xs rounded-2xl bg-muted/20 text-foreground p-6 leading-relaxed border-none shadow-inner" spellCheck={false} />
                  )}
                </div>
              )}

              {activeStep === "output" && (
                <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <div className="flex items-center justify-between">
                    <div className="space-y-1"><h2 className="text-2xl font-black tracking-tight">出参响应定义</h2><p className="text-muted-foreground text-sm">声明返回数据结构</p></div>
                    <div className="flex bg-muted p-1 rounded-xl">
                      <Button variant={outputEditMode === "visual" ? "secondary" : "ghost"} size="sm" className="h-8 rounded-lg text-xs" onClick={() => handleOutputEditModeChange("visual")}>可视化</Button>
                      <Button variant={outputEditMode === "json" ? "secondary" : "ghost"} size="sm" className="h-8 rounded-lg text-xs" onClick={() => handleOutputEditModeChange("json")}>源码</Button>
                    </div>
                  </div>
                  {outputEditMode === "visual" ? (
                    <div className="p-6 border rounded-[2rem] bg-zinc-50/30"><SchemaTreeEditor value={outputTree} onChange={setOutputTree} enableRoute={false} /></div>
                  ) : (
                    <Textarea value={rawOutputJson} onChange={e => setRawOutputJson(e.target.value)} className="min-h-[400px] font-mono text-xs rounded-2xl bg-muted/20 text-foreground p-6 leading-relaxed border-none shadow-inner" spellCheck={false} />
                  )}
                </div>
              )}

              {activeStep === "execution" && (
                <div className="space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <div className="space-y-2"><h2 className="text-2xl font-black tracking-tight">执行与响应配置</h2><p className="text-muted-foreground text-sm">物理请求与摘要模板</p></div>
                  <div className="space-y-8">
                    <div className="grid grid-cols-12 gap-6 p-8 border rounded-[2rem] bg-zinc-50/50">
                      <div className="col-span-4 space-y-2"><Label className="text-xs font-black uppercase tracking-wider">方法</Label><SelectRadix value={payload.execution_profile.method} onValueChange={v => updateProfile("method", v)}><SelectTrigger className="h-11 rounded-xl bg-background"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="GET">GET</SelectItem><SelectItem value="POST">POST</SelectItem></SelectContent></SelectRadix></div>
                      <div className="col-span-8 space-y-2"><Label className="text-xs font-black uppercase tracking-wider">模式</Label><Tabs value={payload.execution_profile.url_mode} onValueChange={v => updateProfile("url_mode", v)} className="w-full"><TabsList className="grid grid-cols-2 h-11 p-1 rounded-xl"><TabsTrigger value="direct">物理直连</TabsTrigger><TabsTrigger value="tag">环境标签</TabsTrigger></TabsList></Tabs></div>
                      <div className="col-span-12">
                        {payload.execution_profile.url_mode === "direct" ? 
                          <Input value={payload.execution_profile.direct_url} onChange={e => updateProfile("direct_url", e.target.value)} placeholder="https://api..." className="h-11 rounded-xl" /> : 
                          <div className="grid grid-cols-2 gap-6"><Input value={payload.execution_profile.sys_label || ""} onChange={e => updateProfile("sys_label", e.target.value)} placeholder="Sys Label" className="h-11 rounded-xl" /><Input value={payload.execution_profile.url_suffix || ""} onChange={e => updateProfile("url_suffix", e.target.value)} placeholder="/api..." className="h-11 rounded-xl" /></div>}
                      </div>
                    </div>
                    <div className="p-8 border rounded-[2rem] bg-zinc-50/50 flex flex-col gap-6">
                      <Label className="text-xs font-black uppercase tracking-wider">安全鉴权</Label>
                      <SelectRadix value={payload.execution_profile.auth_json.type} onValueChange={v => updateAuth("type", v)}><SelectTrigger className="h-11 rounded-xl bg-background"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">无鉴权</SelectItem><SelectItem value="bearer">Bearer Token</SelectItem><SelectItem value="api_key">API Key</SelectItem><SelectItem value="basic">Basic Auth</SelectItem></SelectContent></SelectRadix>
                      {payload.execution_profile.auth_json.type !== "none" && <Input type="password" value={payload.execution_profile.auth_json.token || ""} onChange={e => updateAuth("token", e.target.value)} placeholder="Token / Secret" className="h-11 rounded-xl" />}
                    </div>
                    <div className="space-y-6">
                      <div className="flex items-center gap-2 border-b pb-2">
                        <Code className="w-5 h-5 text-primary" />
                        <h3 className="font-bold text-lg">结果呈现与异常处理</h3>
                      </div>
                      
                      <div className="grid grid-cols-1 gap-6">
                        {/* Success Template */}
                        <div className="p-8 border rounded-[2rem] bg-emerald-500/5 border-emerald-500/10 space-y-4">
                          <div className="flex items-center justify-between">
                            <Label className="text-xs font-black uppercase tracking-wider text-emerald-600">成功响应模板 (Success Template)</Label>
                            <Badge className="bg-emerald-500/10 text-emerald-600 border-none text-[10px]">HTTP 2xx</Badge>
                          </div>
                          <Textarea 
                            value={payload.execution_profile.response_template_json.body || ""} 
                            onChange={e => updateResponseTemplate("body", e.target.value)} 
                            className="min-h-[100px] font-mono text-xs rounded-2xl p-6 bg-white border-emerald-500/20" 
                            placeholder="例如: 查询成功。客户 {{ extracted.name }} 的余额为 {{ extracted.balance }}。" 
                          />
                          <p className="text-[10px] text-muted-foreground italic">当接口返回成功时，渲染此模板作为大模型的最终输入</p>
                        </div>

                        {/* Error Template */}
                        <div className="p-8 border rounded-[2rem] bg-rose-500/5 border-rose-500/10 space-y-4">
                          <div className="flex items-center justify-between">
                            <Label className="text-xs font-black uppercase tracking-wider text-rose-600">异常处理模板 (Error Template)</Label>
                            <Badge className="bg-rose-500/10 text-rose-600 border-none text-[10px]">Non-2xx / Network Error</Badge>
                          </div>
                          <Textarea 
                            value={payload.execution_profile.error_response_template || ""} 
                            onChange={e => updateProfile("error_response_template", e.target.value)} 
                            className="min-h-[100px] font-mono text-xs rounded-2xl p-6 bg-white border-rose-500/20" 
                            placeholder="例如: 抱歉，目标系统暂时无法访问 (错误码: {{ status_code }})，请引导用户核对信息后重试。" 
                          />
                          <p className="text-[10px] text-muted-foreground italic">当接口报错（如 404, 500）或超时时，渲染此模板告知模型如何应对</p>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Navigation Footer */}
              <div className="mt-auto pt-16 flex justify-between items-center border-t border-dashed border-border/60">
                <Button variant="ghost" disabled={activeStep === STEPS[0].id} onClick={() => { const idx = STEPS.findIndex(s => s.id === activeStep); setActiveStep(STEPS[idx - 1].id) }} className="rounded-full px-8 h-11">上一步</Button>
                {activeStep !== STEPS[STEPS.length - 1].id ? 
                  <Button onClick={() => { const idx = STEPS.findIndex(s => s.id === activeStep); setActiveStep(STEPS[idx + 1].id) }} className="rounded-full px-10 h-11 gap-2 shadow-lg">下一步 <ChevronRight className="w-4 h-4" /></Button> : 
                  <Button onClick={handleSave} disabled={isSaving} className="rounded-full px-12 h-11 bg-primary shadow-xl shadow-primary/20">{isSaving ? "正在处理..." : "完成注册"}</Button>}
              </div>
            </div>
          </div>
        </div>

        {/* Protocol Payload Preview Dialog */}
        <Dialog open={isPreviewOpen} onOpenChange={setIsPreviewOpen}>
          <DialogContent className="sm:max-w-4xl max-h-[85vh] flex flex-col p-0 overflow-hidden rounded-[2rem] bg-background text-foreground border shadow-2xl">
            <div className="p-8 border-b flex items-center justify-between">
              <DialogTitle className="text-xl font-black">协议 Payload 预览</DialogTitle>
              <Button variant="ghost" onClick={() => setIsPreviewOpen(false)} className="rounded-full">关闭</Button>
            </div>
            <div className="flex-1 overflow-y-auto p-8 font-mono text-xs bg-muted/5">
              <JSONSyntaxHighlighter data={payload} />
            </div>
          </DialogContent>
        </Dialog>

        {/* Real HTTP Request Preview Dialog */}
        <Dialog open={isRequestPreviewOpen} onOpenChange={setIsRequestPreviewOpen}>
          <DialogContent className="sm:max-w-4xl max-h-[85vh] flex flex-col p-0 overflow-hidden rounded-[2rem] bg-background text-foreground border shadow-2xl">
            <div className="p-8 border-b flex items-center justify-between">
              <div>
                <DialogTitle className="text-xl font-black">真实请求报文预览</DialogTitle>
                <DialogDescription className="text-[10px] mt-1">基于当前配置与示例参数模拟组装出的物理请求内容</DialogDescription>
              </div>
              <Button variant="ghost" onClick={() => setIsRequestPreviewOpen(false)} className="rounded-full">关闭</Button>
            </div>
            <div className="flex-1 overflow-y-auto p-8 space-y-8 bg-zinc-50/50 dark:bg-zinc-950/50">
              <div className="space-y-3">
                <Label className="text-[10px] font-black uppercase tracking-widest text-muted-foreground">URL & Method</Label>
                <div className="p-4 rounded-xl bg-background border flex items-center gap-3 font-mono text-sm overflow-x-auto">
                  <Badge className={cn("px-2 py-0.5", requestPreviewData?.method === "GET" ? "bg-blue-500/10 text-blue-600 border-blue-200" : "bg-green-500/10 text-green-600 border-green-200")}>
                    {requestPreviewData?.method}
                  </Badge>
                  <span className="text-foreground break-all">{requestPreviewData?.url}</span>
                </div>
              </div>

              <div className="space-y-3">
                <Label className="text-[10px] font-black uppercase tracking-widest text-muted-foreground">Request Headers</Label>
                <div className="rounded-xl overflow-hidden border">
                  <JSONSyntaxHighlighter data={requestPreviewData?.headers} />
                </div>
              </div>

              {requestPreviewData?.body && (
                <div className="space-y-3">
                  <Label className="text-[10px] font-black uppercase tracking-widest text-muted-foreground">Request Body</Label>
                  <div className="rounded-xl overflow-hidden border bg-background p-4">
                    <pre className="text-xs font-mono whitespace-pre-wrap break-all leading-relaxed">
                      {(() => {
                        try {
                          return JSON.stringify(JSON.parse(requestPreviewData.body), null, 2)
                        } catch {
                          return requestPreviewData.body
                        }
                      })()}
                    </pre>
                  </div>
                </div>
              )}
            </div>
            <DialogFooter className="p-6 border-t bg-muted/20">
              <p className="text-[10px] text-muted-foreground mr-auto italic flex items-center gap-1.5"><AlertCircle className="w-3 h-3" /> 提示：预览使用了自动生成的 Mock 参数，实际调用由 LLM 驱动。</p>
              <Button onClick={() => setIsRequestPreviewOpen(false)} className="rounded-full px-8">完成核查</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </SheetContent>
    </Sheet>
  )
}
