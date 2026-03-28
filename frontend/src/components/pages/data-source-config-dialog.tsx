"use client"

import { useEffect, useMemo, useRef, useState } from "react"
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
import { Select, type SelectOption } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { cn, getApiUrl } from "@/lib/utils"
import { apiRequest } from "@/lib/api-wrapper"
import { ChevronDown, ChevronRight } from "lucide-react"

type ConnectionMode = "form" | "url"

export interface DataSourceDialogDatabaseRecord {
  id: number
  name: string
  system_id?: number | null
  system_short?: string | null
  system_name?: string | null
  type: string
  url: string
  read_only: boolean
  enabled: boolean
}

export interface DataSourceDialogProfile {
  db_type: string
  display_name: string
  default_port?: number | null
  category: string
  protocol: string
  support_level: string
  aliases: string[]
  driver_packages: string[]
  connection_example: string
  notes: string[]
}

export interface DataSourceDialogSystem {
  id: number
  system_short: string
  system_name: string
}

interface ConnectionFieldOption {
  value: string
  label: string
}

interface ConnectionFieldDefinition {
  key: string
  label: string
  input_type: string
  required: boolean
  placeholder?: string | null
  description?: string | null
  default_value?: string | null
  advanced?: boolean
  secret?: boolean
  options?: ConnectionFieldOption[]
  show_when?: Record<string, string> | null
}

interface ConnectionFormDefinition {
  db_type: string
  display_name: string
  default_port?: number | null
  supports_advanced_mode: boolean
  fields: ConnectionFieldDefinition[]
  defaults: Record<string, string>
}

interface ConnectionTestResult {
  status: string
  message: string
  table_count?: number
}

export interface DataSourceSavePayload {
  name: string
  system_id: number
  type: string
  connection_mode: ConnectionMode
  url?: string
  connection_form: Record<string, string>
  read_only: boolean
  enabled: boolean
}

interface Props {
  open: boolean
  editingRecord: DataSourceDialogDatabaseRecord | null
  systems: DataSourceDialogSystem[]
  profiles: DataSourceDialogProfile[]
  submitting: boolean
  onOpenChange: (open: boolean) => void
  onCreateSystem: () => void
  onSubmit: (payload: DataSourceSavePayload) => Promise<void>
}

interface DialogFormState {
  name: string
  system_id: string
  type: string
  connection_mode: ConnectionMode
  url: string
  connection_form: Record<string, string>
  read_only: boolean
  enabled: boolean
}

function buildInitialState(
  editingRecord: DataSourceDialogDatabaseRecord | null,
  systems: DataSourceDialogSystem[],
  profiles: DataSourceDialogProfile[],
): DialogFormState {
  return {
    name: editingRecord?.name || "",
    system_id: editingRecord?.system_id ? String(editingRecord.system_id) : (systems[0] ? String(systems[0].id) : ""),
    type: editingRecord?.type || profiles[0]?.db_type || "postgresql",
    connection_mode: editingRecord ? "url" : "form",
    url: editingRecord?.url || "",
    connection_form: {},
    read_only: editingRecord?.read_only ?? true,
    enabled: editingRecord?.enabled ?? true,
  }
}

function isFieldVisible(field: ConnectionFieldDefinition, values: Record<string, string>): boolean {
  if (!field.show_when) return true
  return Object.entries(field.show_when).every(([key, expected]) => (values[key] || "") === expected)
}

function mergeSchemaDefaults(
  schema: ConnectionFormDefinition,
  currentValues: Record<string, string>,
): Record<string, string> {
  const merged: Record<string, string> = { ...schema.defaults }
  for (const field of schema.fields) {
    if (field.default_value && merged[field.key] == null) {
      merged[field.key] = field.default_value
    }
  }
  for (const [key, value] of Object.entries(currentValues)) {
    merged[key] = value
  }
  return merged
}

function getVisibleFields(
  schema: ConnectionFormDefinition | null,
  values: Record<string, string>,
  advanced: boolean,
): ConnectionFieldDefinition[] {
  if (!schema) return []
  return schema.fields.filter((field) => {
    if (!advanced && field.advanced) return false
    return isFieldVisible(field, values)
  })
}

function canUseFormMode(
  schema: ConnectionFormDefinition | null,
  values: Record<string, string>,
): boolean {
  if (!schema) return false
  return getVisibleFields(schema, values, true)
    .filter((field) => field.required)
    .every((field) => (values[field.key] || "").trim().length > 0)
}

export function DataSourceConfigDialog({
  open,
  editingRecord,
  systems,
  profiles,
  submitting,
  onOpenChange,
  onCreateSystem,
  onSubmit,
}: Props) {
  const [form, setForm] = useState<DialogFormState>(() => buildInitialState(editingRecord, systems, profiles))
  const [schema, setSchema] = useState<ConnectionFormDefinition | null>(null)
  const [schemaLoading, setSchemaLoading] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [previewUrl, setPreviewUrl] = useState("")
  const [previewMaskedUrl, setPreviewMaskedUrl] = useState("")
  const [previewLoading, setPreviewLoading] = useState(false)
  const [testingConnection, setTestingConnection] = useState(false)
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null)
  const [currentStep, setCurrentStep] = useState(1)
  const initializedKeyRef = useRef<string>("")

  const selectedProfile = useMemo(
    () => profiles.find((item) => item.db_type === form.type) ?? null,
    [profiles, form.type],
  )

  const systemOptions: SelectOption[] = useMemo(
    () =>
      systems.map((item) => ({
        value: String(item.id),
        label: item.system_name,
        description: item.system_short,
      })),
    [systems],
  )

  const typeOptions: SelectOption[] = useMemo(
    () =>
      profiles.map((item) => ({
        value: item.db_type,
        label: item.display_name,
        description: `${item.category} / ${item.protocol}`,
      })),
    [profiles],
  )

  useEffect(() => {
    if (!open) {
      initializedKeyRef.current = ""
      setPreviewUrl("")
      setPreviewMaskedUrl("")
      setTestResult(null)
      setSchema(null)
      return
    }
    setForm(buildInitialState(editingRecord, systems, profiles))
    setShowAdvanced(false)
    setCurrentStep(1)
    setPreviewUrl("")
    setPreviewMaskedUrl("")
    setTestResult(null)
  }, [open, editingRecord, profiles, systems])

  useEffect(() => {
    if (!open || !form.type) return
    let active = true
    const loadSchema = async () => {
      setSchemaLoading(true)
      try {
        const response = await apiRequest(
          `${getApiUrl()}/api/text2sql/database-types/${encodeURIComponent(form.type)}/connection-form`,
          { headers: {} },
        )
        const payload = await response.json().catch(() => ({}))
        if (!response.ok) {
          throw new Error(payload.detail || "加载连接表单失败")
        }
        if (!active) return
        setSchema(payload)
      } catch (error) {
        if (!active) return
        toast.error(error instanceof Error ? error.message : "加载连接表单失败")
        setSchema(null)
      } finally {
        if (active) {
          setSchemaLoading(false)
        }
      }
    }
    void loadSchema()
    return () => {
      active = false
    }
  }, [open, form.type])

  useEffect(() => {
    if (!open || !schema) return
    const initKey = editingRecord
      ? `edit:${editingRecord.id}:${schema.db_type}:${editingRecord.url}`
      : `create:${schema.db_type}`

    if (initializedKeyRef.current === initKey) return
    initializedKeyRef.current = initKey

    if (!editingRecord) {
      setForm((prev) => ({
        ...prev,
        connection_mode: "form",
        connection_form: mergeSchemaDefaults(schema, prev.connection_form),
      }))
      return
    }

    let active = true
    const parseUrl = async () => {
      try {
        const response = await apiRequest(`${getApiUrl()}/api/text2sql/connection/parse`, {
          method: "POST",
          headers: {},
          body: JSON.stringify({
            db_type: editingRecord.type,
            url: editingRecord.url,
          }),
        })
        const payload = await response.json().catch(() => ({}))
        if (!response.ok) {
          throw new Error(payload.detail || "解析连接字符串失败")
        }
        if (!active) return
        setForm((prev) => ({
          ...prev,
          connection_mode: payload.can_use_form_mode ? "form" : "url",
          url: editingRecord.url,
          connection_form: mergeSchemaDefaults(schema, payload.form || {}),
        }))
        setPreviewUrl(editingRecord.url)
        setPreviewMaskedUrl(payload.masked_url || editingRecord.url)
      } catch {
        if (!active) return
        setForm((prev) => ({
          ...prev,
          connection_mode: "url",
          url: editingRecord.url,
          connection_form: mergeSchemaDefaults(schema, prev.connection_form),
        }))
        setPreviewUrl(editingRecord.url)
        setPreviewMaskedUrl(editingRecord.url)
      }
    }
    void parseUrl()
    return () => {
      active = false
    }
  }, [open, schema, editingRecord])

  useEffect(() => {
    if (!open || !schema) return
    if (form.connection_mode !== "form") {
      setPreviewUrl(form.url)
      setPreviewMaskedUrl(form.url)
      return
    }

    if (!canUseFormMode(schema, form.connection_form)) {
      setPreviewUrl("")
      setPreviewMaskedUrl("")
      return
    }

    let active = true
    const timer = window.setTimeout(async () => {
      setPreviewLoading(true)
      try {
        const response = await apiRequest(`${getApiUrl()}/api/text2sql/connection/preview`, {
          method: "POST",
          headers: {},
          body: JSON.stringify({
            db_type: form.type,
            connection_mode: "form",
            connection_form: form.connection_form,
          }),
        })
        const payload = await response.json().catch(() => ({}))
        if (!response.ok) {
          throw new Error(payload.detail || "生成连接字符串预览失败")
        }
        if (!active) return
        setPreviewUrl(payload.url || "")
        setPreviewMaskedUrl(payload.masked_url || payload.url || "")
      } catch {
        if (!active) return
        setPreviewUrl("")
        setPreviewMaskedUrl("")
      } finally {
        if (active) {
          setPreviewLoading(false)
        }
      }
    }, 250)

    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [open, schema, form.type, form.connection_mode, form.connection_form, form.url])

  const visibleBaseFields = useMemo(
    () => getVisibleFields(schema, form.connection_form, false),
    [schema, form.connection_form],
  )
  const visibleAdvancedFields = useMemo(
    () => getVisibleFields(schema, form.connection_form, true).filter((field) => field.advanced),
    [schema, form.connection_form],
  )

  const canSubmit =
    form.name.trim().length > 0 &&
    form.system_id.trim().length > 0 &&
    form.type.trim().length > 0 &&
    (
      form.connection_mode === "url"
        ? form.url.trim().length > 0
        : canUseFormMode(schema, form.connection_form)
    )

  const canTest =
    form.connection_mode === "url"
      ? form.url.trim().length > 0
      : canUseFormMode(schema, form.connection_form)

  const setConnectionValue = (key: string, value: string) => {
    setForm((prev) => ({
      ...prev,
      connection_form: {
        ...prev.connection_form,
        [key]: value,
      },
    }))
    setTestResult(null)
  }

  const renderField = (field: ConnectionFieldDefinition) => {
    const value = form.connection_form[field.key] || ""
    if (field.input_type === "select") {
      const options: SelectOption[] = (field.options || []).map((item) => ({
        value: item.value,
        label: item.label,
      }))
      return (
        <div key={field.key} className="space-y-2">
          <Label>{field.label}</Label>
          <Select
            value={value || field.default_value || ""}
            onValueChange={(nextValue) => setConnectionValue(field.key, nextValue)}
            options={options}
            placeholder={`请选择${field.label}`}
          />
          {field.description ? <div className="text-xs text-muted-foreground">{field.description}</div> : null}
        </div>
      )
    }

    if (field.input_type === "textarea") {
      return (
        <div key={field.key} className="space-y-2">
          <Label>{field.label}</Label>
          <Textarea
            rows={4}
            value={value}
            onChange={(event) => setConnectionValue(field.key, event.target.value)}
            placeholder={field.placeholder || ""}
          />
          {field.description ? <div className="text-xs text-muted-foreground">{field.description}</div> : null}
        </div>
      )
    }

    return (
      <div key={field.key} className="space-y-2">
        <Label>{field.label}</Label>
        <Input
          type={field.secret ? "password" : field.input_type === "number" ? "number" : "text"}
          value={value}
          onChange={(event) => setConnectionValue(field.key, event.target.value)}
          placeholder={field.placeholder || ""}
        />
        {field.description ? <div className="text-xs text-muted-foreground">{field.description}</div> : null}
      </div>
    )
  }

  const handleTestConnection = async () => {
    setTestingConnection(true)
    setTestResult(null)
    try {
      const response = await apiRequest(`${getApiUrl()}/api/text2sql/connection/test`, {
        method: "POST",
        headers: {},
        body: JSON.stringify({
          db_type: form.type,
          connection_mode: form.connection_mode,
          url: form.connection_mode === "url" ? form.url : undefined,
          connection_form: form.connection_form,
          read_only: form.read_only,
        }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || "连接测试失败")
      }
      setPreviewUrl(payload.url || previewUrl)
      setPreviewMaskedUrl(payload.masked_url || previewMaskedUrl)
      setTestResult({
        status: payload.status || "connected",
        message: payload.message || "连接测试成功",
        table_count: payload.table_count,
      })
      toast.success(payload.message || "连接测试成功")
    } catch (error) {
      const message = error instanceof Error ? error.message : "连接测试失败"
      setTestResult({ status: "error", message })
      toast.error(message)
    } finally {
      setTestingConnection(false)
    }
  }

  const handleSubmit = async () => {
    if (!canSubmit) {
      toast.error("请先补全数据源基础信息和连接配置")
      return
    }

    await onSubmit({
      name: form.name.trim(),
      system_id: Number(form.system_id),
      type: form.type,
      connection_mode: form.connection_mode,
      url: form.connection_mode === "url" ? form.url.trim() : previewUrl || undefined,
      connection_form: form.connection_form,
      read_only: form.read_only,
      enabled: form.enabled,
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-hidden p-0">
        <div className="flex max-h-[90vh] flex-col">
          <div className="border-b border-border/70 px-6 py-5">
            <DialogHeader>
              <div className="flex items-center justify-between">
                <div>
                  <DialogTitle>{editingRecord ? "编辑数据源" : "新增数据源"}</DialogTitle>
                  <DialogDescription className="mt-1">
                    {currentStep === 1 && "第一步：基本信息与类型"}
                    {currentStep === 2 && "第二步：连接参数配置"}
                    {currentStep === 3 && "第三步：高级选项与预览"}
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
                                                      : "bg-white border border-border text-muted-foreground"                      )}
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
                    <Label className="text-sm font-semibold">数据源名称</Label>
                    <Input
                      value={form.name}
                      onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
                      placeholder="例如：CRM 主库"
                    />
                  </div>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <Label className="text-sm font-semibold">所属系统</Label>
                      <Button variant="ghost" className="h-auto px-0 text-xs" onClick={onCreateSystem}>
                        新增系统
                      </Button>
                    </div>
                    <Select
                      value={form.system_id}
                      onValueChange={(value) => setForm((prev) => ({ ...prev, system_id: value }))}
                      options={systemOptions}
                      placeholder="请选择所属系统"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label className="text-sm font-semibold">数据库类型</Label>
                  <Select
                    value={form.type}
                    onValueChange={(value) =>
                      setForm((prev) => ({
                        ...prev,
                        type: value,
                        connection_mode: prev.connection_mode === "url" ? "url" : "form",
                        url: prev.connection_mode === "url" ? prev.url : "",
                        connection_form: {},
                      }))
                    }
                    options={typeOptions}
                    placeholder="请选择数据库类型"
                  />
                  {selectedProfile && (
                    <div className="rounded-lg bg-primary/5 p-3 mt-2">
                      <div className="text-xs font-medium text-muted-foreground">支持详情</div>
                      <div className="mt-1 text-sm">{selectedProfile.display_name} ({selectedProfile.protocol})</div>
                      <div className="mt-1 text-[11px] text-muted-foreground">{selectedProfile.notes[0]}</div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {currentStep === 2 && (
              <div className="space-y-5 animate-in fade-in slide-in-from-right-4 duration-300">
                <Tabs
                  value={form.connection_mode}
                  onValueChange={(value) => setForm((prev) => ({ ...prev, connection_mode: value as ConnectionMode }))}
                  className="w-full"
                >
                  <TabsList className="grid w-full grid-cols-2">
                    <TabsTrigger value="form">普通模式 (表单)</TabsTrigger>
                    <TabsTrigger value="url">高级模式 (URL)</TabsTrigger>
                  </TabsList>
                  <TabsContent value="form" className="space-y-4 pt-4">
                    {schemaLoading ? (
                      <div className="py-10 text-center text-sm text-muted-foreground">加载表单定义中...</div>
                    ) : (
                      <div className="grid grid-cols-2 gap-4">
                        {visibleBaseFields.map(renderField)}
                      </div>
                    )}
                  </TabsContent>
                  <TabsContent value="url" className="space-y-4 pt-4">
                    <div className="space-y-2">
                      <Label className="text-sm font-semibold">完整连接字符串</Label>
                      <Textarea
                        rows={6}
                        value={form.url}
                        onChange={(event) => {
                          setForm((prev) => ({ ...prev, url: event.target.value }))
                          setTestResult(null)
                        }}
                        placeholder={selectedProfile?.connection_example || "请输入完整连接字符串"}
                        className="font-mono text-xs"
                      />
                      <p className="text-[11px] text-muted-foreground">适用于特殊驱动、云厂商参数、ODBC 等高级场景。</p>
                    </div>
                  </TabsContent>
                </Tabs>
              </div>
            )}

            {currentStep === 3 && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
                <div className="grid grid-cols-2 gap-4">
                   <div className="flex items-center justify-between rounded-lg border border-border p-3">
                      <div>
                        <div className="text-sm font-medium">只读模式</div>
                        <div className="text-[10px] text-muted-foreground">启用后仅允许执行 SELECT。</div>
                      </div>
                      <Switch
                        checked={form.read_only}
                        onCheckedChange={(checked) => setForm((prev) => ({ ...prev, read_only: checked }))}
                      />
                   </div>
                   <div className="flex items-center justify-between rounded-lg border border-border p-3">
                      <div>
                        <div className="text-sm font-medium">启用状态</div>
                        <div className="text-[10px] text-muted-foreground">控制数据源是否对 Agent 可见。</div>
                      </div>
                      <Switch
                        checked={form.enabled}
                        onCheckedChange={(checked) => setForm((prev) => ({ ...prev, enabled: checked }))}
                      />
                   </div>
                </div>

                <div className="rounded-xl border border-border bg-white p-4">
                  <div className="flex items-center justify-between">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">连接预览</div>
                    {previewLoading && <div className="text-[10px] animate-pulse">更新中...</div>}
                  </div>
                  <Textarea
                    rows={3}
                    className="mt-2 font-mono text-[11px] leading-relaxed bg-background/50"
                    value={previewMaskedUrl || previewUrl || "等待输入配置..."}
                    readOnly
                  />
                </div>

                {testResult && (
                  <div className={cn(
                    "rounded-lg border p-3 text-xs",
                    testResult.status === "connected" ? "border-green-500/20 bg-green-500/5 text-green-600" : "border-red-500/20 bg-red-500/5 text-red-600"
                  )}>
                    <div className="font-semibold">{testResult.status === "connected" ? "连接测试成功" : "连接测试失败"}</div>
                    <div className="mt-1">{testResult.message}</div>
                    {testResult.table_count != null && (
                      <div className="mt-1 opacity-80">识别到顶层对象: {testResult.table_count}</div>
                    )}
                  </div>
                )}
                
                {visibleAdvancedFields.length > 0 && (
                  <div className="space-y-3 rounded-xl border border-border bg-white p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium">高级选项</div>
                      <Button 
                        variant="outline" 
                        size="sm" 
                        onClick={() => setShowAdvanced(!showAdvanced)}
                      >
                        {showAdvanced ? "收起" : "展开"}
                      </Button>
                    </div>
                    {showAdvanced && (
                      <div className="grid grid-cols-2 gap-4 pt-2 animate-in fade-in slide-in-from-top-2 duration-200">
                        {visibleAdvancedFields.map(renderField)}
                      </div>
                    )}
                  </div>
                )}
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
                <Button variant="ghost" onClick={() => onOpenChange(false)}>
                  取消
                </Button>
                {currentStep === 2 && canTest && (
                   <Button variant="outline" onClick={handleTestConnection} disabled={testingConnection}>
                      {testingConnection ? "测试中..." : "测试连接"}
                   </Button>
                )}
                {currentStep < 3 ? (
                  <Button 
                    onClick={() => setCurrentStep(prev => prev + 1)}
                    disabled={currentStep === 1 && (!form.name.trim() || !form.system_id.trim())}
                  >
                    下一步
                  </Button>
                ) : (
                  <div className="flex gap-2">
                    <Button variant="outline" onClick={handleTestConnection} disabled={testingConnection}>
                      测试连接
                    </Button>
                    <Button onClick={handleSubmit} disabled={submitting || !canSubmit}>
                      {submitting ? "保存中..." : "完成并保存"}
                    </Button>
                  </div>
                )}
              </div>
            </DialogFooter>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
