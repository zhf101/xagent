"use client"

import React, { useCallback, useEffect, useState } from "react"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select as SelectRadix, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select-radix"
import { JSONSyntaxHighlighter } from "@/components/ui/json-syntax-highlighter"
import { toast } from "sonner"
import { getApiUrl } from "@/lib/utils"
import { apiRequest } from "@/lib/api-wrapper"
import { getApiErrorMessage, getApprovalSubmissionMessage } from "@/lib/api-errors"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Save, AlertCircle, Eye } from "lucide-react"
import { GdpHttpAssetPayload } from "../gdp-types"

interface GdpHttpConfigDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
  assetId?: number
}

// Default payload matching backend expectations
const defaultPayload = (): GdpHttpAssetPayload => ({
  resource: {
    resource_key: "",
    system_short: "",
    visibility: "private",
    summary: "",
    tags_json: []
  },
  tool_contract: {
    tool_name: "",
    tool_description: "",
    input_schema_json: { type: "object", properties: {} },
    output_schema_json: { type: "object", properties: {} },
    annotations_json: {}
  },
  execution_profile: {
    method: "POST",
    url_mode: "direct",
    direct_url: "",
    sys_label: "",
    url_suffix: "",
    args_position_json: {},
    request_template_json: {},
    response_template_json: {},
    error_response_template: "",
    auth_json: { type: "none" },
    headers_json: [],
    timeout_seconds: 30
  }
})

const steps = [
  { id: "step1", label: "基础与协议层", desc: "资源管理与工具声明" },
  { id: "step2", label: "入参与出参", desc: "复杂嵌套数据结构" },
  { id: "step3", label: "执行层-网络", desc: "路由与基础网络配置" },
  { id: "step4", label: "协议转化", desc: "请求响应映射组装" },
]

export function GdpHttpConfigDrawer({ open, onOpenChange, onSaved, assetId }: GdpHttpConfigDrawerProps) {
  const [activeStep, setActiveStep] = useState("step1")
  const [payload, setPayload] = useState<GdpHttpAssetPayload>(defaultPayload())
  const [isSaving, setIsSaving] = useState(false)
  const [isPreviewOpen, setIsPreviewOpen] = useState(false)

  // Editor specific states for JSON textareas
  const [inputSchemaText, setInputSchemaText] = useState("")
  const [outputSchemaText, setOutputSchemaText] = useState("")
  const [argsPositionText, setArgsPositionText] = useState("")
  const [reqTemplateText, setReqTemplateText] = useState("")
  const [resTemplateText, setResTemplateText] = useState("")
  const [headersText, setHeadersText] = useState("")
  const [annotationsText, setAnnotationsText] = useState("")

  const syncTextFromPayload = (data: GdpHttpAssetPayload) => {
    setInputSchemaText(JSON.stringify(data.tool_contract?.input_schema_json || {}, null, 2))
    setOutputSchemaText(JSON.stringify(data.tool_contract?.output_schema_json || {}, null, 2))
    setAnnotationsText(JSON.stringify(data.tool_contract?.annotations_json || {}, null, 2))
    setArgsPositionText(JSON.stringify(data.execution_profile?.args_position_json || {}, null, 2))
    setReqTemplateText(JSON.stringify(data.execution_profile?.request_template_json || {}, null, 2))
    setResTemplateText(JSON.stringify(data.execution_profile?.response_template_json || {}, null, 2))
    setHeadersText(JSON.stringify(data.execution_profile?.headers_json || {}, null, 2))
  }

  const syncPayloadFromText = () => {
    try {
      const p = { ...payload }
      p.tool_contract.input_schema_json = JSON.parse(inputSchemaText || "{}")
      p.tool_contract.output_schema_json = JSON.parse(outputSchemaText || "{}")
      p.tool_contract.annotations_json = JSON.parse(annotationsText || "{}")
      p.execution_profile.args_position_json = JSON.parse(argsPositionText || "{}")
      p.execution_profile.request_template_json = JSON.parse(reqTemplateText || "{}")
      p.execution_profile.response_template_json = JSON.parse(resTemplateText || "{}")
      p.execution_profile.headers_json = JSON.parse(headersText || "{}")
      setPayload(p)
      return true
    } catch {
      toast.error("JSON 格式校验失败，请检查所有 JSON 编辑器内容")
      return false
    }
  }

  const normalizeVisibility = (visibility: unknown): "private" | "shared" | "global" => {
    if (visibility === "shared" || visibility === "global") {
      return visibility
    }
    return "private"
  }

  const fetchAsset = useCallback(async (id: number) => {
    try {
      const res = await apiRequest(`${getApiUrl()}/api/v1/gdp/http-assets/${id}`)
      if (res.ok) {
        const json = await res.json()
        const data = json.data
        // Reconstruct payload format
        const fetchedPayload: GdpHttpAssetPayload = {
          resource: {
            resource_key: data.resource_key,
            system_short: data.system_short,
            visibility: normalizeVisibility(data.visibility),
            summary: data.summary,
            tags_json: data.tags_json || []
          },
          tool_contract: {
            tool_name: data.tool_name,
            tool_description: data.tool_description,
            input_schema_json: data.input_schema_json || {},
            output_schema_json: data.output_schema_json || {},
            annotations_json: data.annotations_json || {}
          },
          execution_profile: {
            method: data.method,
            url_mode: data.url_mode,
            direct_url: data.direct_url,
            sys_label: data.sys_label,
            url_suffix: data.url_suffix,
            args_position_json: data.args_position_json || {},
            request_template_json: data.request_template_json || {},
            response_template_json: data.response_template_json || {},
            error_response_template: data.error_response_template || "",
            auth_json: data.auth_json?.type ? data.auth_json : { type: "none" },
            headers_json: Array.isArray(data.headers_json) ? data.headers_json : [],
            timeout_seconds: data.timeout_seconds || 30
          }
        }
        setPayload(fetchedPayload)
        syncTextFromPayload(fetchedPayload)
      } else {
        toast.error("加载资产失败")
      }
    } catch (error) {
      console.error(error)
    }
  }, [])

  useEffect(() => {
    if (open) {
      if (assetId) {
        fetchAsset(assetId)
      } else {
        setPayload(defaultPayload())
        syncTextFromPayload(defaultPayload())
        setActiveStep("step1")
      }
    }
  }, [open, assetId, fetchAsset])

  const updateField = (
    category: "resource" | "tool_contract" | "execution_profile",
    field: string,
    value: unknown
  ) => {
    setPayload(prev => ({
      ...prev,
      [category]: {
        ...prev[category],
        [field]: value
      }
    }) as GdpHttpAssetPayload)
  }

  const validate = () => {
    if (!syncPayloadFromText()) return false
    if (!payload.resource.resource_key) { toast.error("资源唯一标识必填"); return false }
    if (!payload.tool_contract.tool_name) { toast.error("工具名称必填"); return false }
    if (payload.execution_profile.url_mode === 'direct' && !payload.execution_profile.direct_url) {
      toast.error("Direct URL 模式下必须填写 URL")
      return false
    }
    if (payload.execution_profile.url_mode === 'tag' && !payload.execution_profile.sys_label) {
      toast.error("Tag 模式下必须填写 System Label")
      return false
    }
    return true
  }

  const handleSave = async () => {
    if (!validate()) return
    setIsSaving(true)
    
    try {
      const url = assetId 
        ? `${getApiUrl()}/api/v1/gdp/http-assets/${assetId}` 
        : `${getApiUrl()}/api/v1/gdp/http-assets`
      const method = assetId ? 'PUT' : 'POST'
      
      const res = await apiRequest(url, {
        method,
        body: JSON.stringify(payload),
        headers: { 'Content-Type': 'application/json' }
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
        const err = await res.json()
        toast.error(getApiErrorMessage(err, "保存失败"))
      }
    } catch {
      toast.error("保存过程发生异常")
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-[900px] w-[90vw] p-0 flex flex-col h-full bg-background border-l border-border">
        <SheetHeader className="px-6 py-4 border-b border-border bg-card/50 flex-shrink-0">
          <div className="flex items-center justify-between">
            <div>
              <SheetTitle className="text-xl font-bold">{assetId ? "编辑 GDP HTTP 资产" : "注册 GDP HTTP 资产"}</SheetTitle>
              <p className="text-sm text-muted-foreground mt-1">一表三层协议配置模型 (Resource / Tool Contract / Execution Profile)</p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={() => setIsPreviewOpen(!isPreviewOpen)}>
                <Eye className="w-4 h-4 mr-2" />
                {isPreviewOpen ? "关闭预览" : "预览报文"}
              </Button>
              <Button onClick={handleSave} disabled={isSaving}>
                <Save className="w-4 h-4 mr-2" />
                {isSaving ? "保存中..." : (assetId ? "更新" : "注册")}
              </Button>
            </div>
          </div>
        </SheetHeader>

        <div className="flex flex-1 overflow-hidden">
          {/* 左侧导航 */}
          <div className="w-48 border-r border-border bg-card/20 flex flex-col overflow-y-auto hidden sm:block">
            <div className="p-3 space-y-1">
              {steps.map(step => (
                <button
                  key={step.id}
                  onClick={() => setActiveStep(step.id)}
                  className={`w-full text-left px-3 py-2 rounded-lg transition-colors duration-200 ${
                    activeStep === step.id
                      ? "bg-primary/10 text-primary font-medium"
                      : "hover:bg-muted text-muted-foreground"
                  }`}
                >
                  <div className="text-sm">{step.label}</div>
                  <div className="text-[10px] opacity-70 truncate mt-0.5">{step.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* 主体内容 */}
          <ScrollArea className="flex-1 relative bg-background">
            <div className="p-6 pb-24 max-w-3xl mx-auto space-y-8">
              
              {isPreviewOpen ? (
                <div className="space-y-4 animate-in fade-in">
                  <div className="flex items-center justify-between">
                    <h3 className="font-bold">最终提交报文预览</h3>
                    <Button variant="ghost" size="sm" onClick={() => syncPayloadFromText()}>更新预览</Button>
                  </div>
                  <JSONSyntaxHighlighter data={payload} />
                </div>
              ) : (
                <div className="animate-in fade-in slide-in-from-right-4 duration-300">
                  
                  {activeStep === "step1" && (
                    <div className="space-y-6">
                      <div className="border border-border rounded-lg p-5 space-y-5 bg-card/30">
                        <div className="flex items-center gap-2 border-b border-border pb-3">
                          <h3 className="font-bold text-foreground">宿主管理层 (Resource)</h3>
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <Label>资源唯一标识 (Resource Key) <span className="text-destructive">*</span></Label>
                            <Input 
                              placeholder="e.g. jql_query_asset" 
                              value={payload.resource.resource_key}
                              onChange={e => updateField('resource', 'resource_key', e.target.value)}
                            />
                          </div>
                          <div className="space-y-2">
                            <Label>归属系统 (System Short)</Label>
                            <Input 
                              placeholder="e.g. crm" 
                              value={payload.resource.system_short}
                              onChange={e => updateField('resource', 'system_short', e.target.value)}
                            />
                          </div>
                        </div>
                        <div className="space-y-2">
                          <Label>摘要 (Summary)</Label>
                          <Input 
                            placeholder="资源简短摘要" 
                            value={payload.resource.summary}
                            onChange={e => updateField('resource', 'summary', e.target.value)}
                          />
                        </div>
                      </div>

                      <div className="border border-border rounded-lg p-5 space-y-5 bg-card/30">
                        <div className="flex items-center gap-2 border-b border-border pb-3">
                          <h3 className="font-bold text-foreground">大模型可见层 (Tool Contract)</h3>
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <Label>工具名称 (Tool Name) <span className="text-destructive">*</span></Label>
                            <Input 
                              placeholder="供大模型调用的函数名" 
                              value={payload.tool_contract.tool_name}
                              onChange={e => updateField('tool_contract', 'tool_name', e.target.value)}
                            />
                          </div>
                        </div>
                        <div className="space-y-2">
                          <Label>工具描述 (Tool Description) <span className="text-destructive">*</span></Label>
                          <Textarea 
                            placeholder="给大模型看的工具功能说明" 
                            className="min-h-[80px]"
                            value={payload.tool_contract.tool_description}
                            onChange={e => updateField('tool_contract', 'tool_description', e.target.value)}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label>Annotations (JSON)</Label>
                          <Textarea 
                            className="font-mono text-xs min-h-[100px]"
                            value={annotationsText}
                            onChange={e => setAnnotationsText(e.target.value)}
                            placeholder='{"requires_confirmation": true}'
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {activeStep === "step2" && (
                    <div className="space-y-6">
                      <div className="flex items-center bg-blue-500/10 text-blue-500 p-3 rounded-lg border border-blue-500/20 text-sm">
                        <AlertCircle className="w-4 h-4 mr-2" />
                        前端支持复杂嵌套的 JSON Schema 定义。请按 JSON Schema 规范填写 Input / Output Schema。
                      </div>
                      
                      <div className="space-y-4">
                        <div className="flex items-center justify-between">
                          <Label>Input Schema (JSON Schema)</Label>
                          <span className="text-[10px] text-muted-foreground">用于定义大模型入参结构</span>
                        </div>
                        <Textarea 
                          className="font-mono text-xs min-h-[250px] bg-secondary/30"
                          value={inputSchemaText}
                          onChange={e => setInputSchemaText(e.target.value)}
                          placeholder='{ "type": "object", "properties": { "query": { "type": "string" } }, "required": ["query"] }'
                        />
                      </div>

                      <div className="space-y-4 pt-4">
                        <div className="flex items-center justify-between">
                          <Label>Output Schema (JSON Schema)</Label>
                          <span className="text-[10px] text-muted-foreground">用于约束响应结构</span>
                        </div>
                        <Textarea 
                          className="font-mono text-xs min-h-[250px] bg-secondary/30"
                          value={outputSchemaText}
                          onChange={e => setOutputSchemaText(e.target.value)}
                          placeholder='{ "type": "object", "properties": { "result": { "type": "string" } } }'
                        />
                      </div>
                    </div>
                  )}

                  {activeStep === "step3" && (
                    <div className="space-y-6">
                      <div className="border border-border rounded-lg p-5 space-y-5 bg-card/30">
                        <div className="flex items-center gap-2 border-b border-border pb-3">
                          <h3 className="font-bold text-foreground">路由与基础网络</h3>
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <Label>请求方法 (Method)</Label>
                            <SelectRadix 
                              value={payload.execution_profile.method} 
                              onValueChange={v => updateField('execution_profile', 'method', v)}
                            >
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {['GET', 'POST', 'PUT', 'DELETE', 'PATCH'].map(m => (
                                  <SelectItem key={m} value={m}>{m}</SelectItem>
                                ))}
                              </SelectContent>
                            </SelectRadix>
                          </div>
                          <div className="space-y-2">
                            <Label>URL 模式</Label>
                            <SelectRadix 
                              value={payload.execution_profile.url_mode} 
                              onValueChange={v => updateField('execution_profile', 'url_mode', v)}
                            >
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="direct">Direct (完整 URL)</SelectItem>
                                <SelectItem value="tag">Tag (基于系统的标识路由)</SelectItem>
                              </SelectContent>
                            </SelectRadix>
                          </div>
                        </div>

                        {payload.execution_profile.url_mode === 'direct' ? (
                          <div className="space-y-2">
                            <Label>直接请求地址 (Direct URL) <span className="text-destructive">*</span></Label>
                            <Input 
                              placeholder="https://api.example.com/v1/data" 
                              value={payload.execution_profile.direct_url || ''}
                              onChange={e => updateField('execution_profile', 'direct_url', e.target.value)}
                            />
                          </div>
                        ) : (
                          <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                              <Label>系统标识 (Sys Label) <span className="text-destructive">*</span></Label>
                              <Input 
                                placeholder="e.g. user_center" 
                                value={payload.execution_profile.sys_label || ''}
                                onChange={e => updateField('execution_profile', 'sys_label', e.target.value)}
                              />
                            </div>
                            <div className="space-y-2">
                              <Label>URL Suffix</Label>
                              <Input 
                                placeholder="e.g. /api/v1/users" 
                                value={payload.execution_profile.url_suffix || ''}
                                onChange={e => updateField('execution_profile', 'url_suffix', e.target.value)}
                              />
                            </div>
                          </div>
                        )}

                        <div className="space-y-2 pt-2 border-t border-border">
                          <Label>请求头 Headers (JSON)</Label>
                          <Textarea 
                            className="font-mono text-xs min-h-[100px]"
                            value={headersText}
                            onChange={e => setHeadersText(e.target.value)}
                            placeholder='{"Authorization": "Bearer token", "Content-Type": "application/json"}'
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {activeStep === "step4" && (
                    <div className="space-y-6">
                      <div className="space-y-4">
                        <div className="flex items-center justify-between">
                          <Label>Args Position (入参映射)</Label>
                          <span className="text-[10px] text-muted-foreground">定义入参如何填充到 HTTP 请求中</span>
                        </div>
                        <Textarea 
                          className="font-mono text-xs min-h-[150px] bg-secondary/30"
                          value={argsPositionText}
                          onChange={e => setArgsPositionText(e.target.value)}
                          placeholder='{"query": {"in": "query", "name": "q"}, "id": {"in": "path"}}'
                        />
                      </div>

                      <div className="space-y-4">
                        <Label>请求模板 (Request Template JSON)</Label>
                        <Textarea 
                          className="font-mono text-xs min-h-[150px]"
                          value={reqTemplateText}
                          onChange={e => setReqTemplateText(e.target.value)}
                          placeholder='{"body": {"fixed_param": "value", "dynamic": "{{args.param}}" }}'
                        />
                      </div>

                      <div className="space-y-4">
                        <Label>响应模板 (Response Template JSON)</Label>
                        <Textarea 
                          className="font-mono text-xs min-h-[150px]"
                          value={resTemplateText}
                          onChange={e => setResTemplateText(e.target.value)}
                          placeholder='{"result": "{{res.body.data.list}}" }'
                        />
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </ScrollArea>
        </div>
      </SheetContent>
    </Sheet>
  )
}
