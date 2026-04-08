import React, { useCallback, useEffect, useMemo, useState } from "react"
import { AlertCircle, CheckCircle2, Loader2, ShieldCheck, Sparkles } from "lucide-react"
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { Select, type SelectOption } from "@/components/ui/select"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { toast } from "sonner"
import { getApiUrl } from "@/lib/utils"
import { apiRequest } from "@/lib/api-wrapper"
import {
  getApiErrorMessage,
} from "@/lib/api-errors"

interface DatabaseFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  databaseId?: number
  onSuccess: () => void
}

interface DatabaseProfile {
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
  advanced: boolean
  secret: boolean
  options: ConnectionFieldOption[]
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

interface DatabaseDetail {
  id: number
  name: string
  system_short: string
  database_name?: string | null
  env: string
  type: string
  url: string
  read_only: boolean
}

interface ConnectionPreviewResponse {
  url: string
  masked_url: string
  db_type: string
}

interface SystemOption {
  system_short: string
  display_name: string
  description?: string | null
  status: string
}

type ConnectionFormValues = Record<string, string>
type TestFeedback = {
  type: "success" | "error"
  message: string
}

type DialogState = {
  name: string
  system_short: string
  database_name: string
  env: string
  type: string
  read_only: boolean
}

const EMPTY_DIALOG_STATE: DialogState = {
  name: "",
  system_short: "",
  database_name: "",
  env: "",
  type: "",
  read_only: true,
}

function normalizeFieldValue(value: unknown): string {
  if (value === null || value === undefined) return ""
  return String(value)
}

function isFieldVisible(field: ConnectionFieldDefinition, values: ConnectionFormValues): boolean {
  if (!field.show_when) return true
  return Object.entries(field.show_when).every(([dependencyKey, expectedValue]) => {
    return normalizeFieldValue(values[dependencyKey]) === expectedValue
  })
}

function buildFormValues(definition: ConnectionFormDefinition, seed?: Record<string, unknown>): ConnectionFormValues {
  const nextValues: ConnectionFormValues = {}
  definition.fields.forEach(field => {
    nextValues[field.key] = normalizeFieldValue(
      seed?.[field.key] ?? definition.defaults[field.key] ?? field.default_value ?? ""
    )
  })
  return nextValues
}

function extractPersistedSecrets(
  definition: ConnectionFormDefinition,
  parsedValues: Record<string, unknown>
): ConnectionFormValues {
  const secrets: ConnectionFormValues = {}
  definition.fields.forEach(field => {
    if (!field.secret) return
    const value = normalizeFieldValue(parsedValues[field.key])
    if (value) {
      secrets[field.key] = value
    }
  })
  return secrets
}

function hasAdvancedContent(
  definition: ConnectionFormDefinition,
  values: Record<string, unknown>
): boolean {
  return definition.fields.some(field => {
    if (!field.advanced) return false
    return normalizeFieldValue(values[field.key]).trim().length > 0
  })
}

export function DatabaseFormDialog({ open, onOpenChange, databaseId, onSuccess }: DatabaseFormDialogProps) {
  const [profiles, setProfiles] = useState<DatabaseProfile[]>([])
  const [systemOptions, setSystemOptions] = useState<SystemOption[]>([])
  const [systemOptionsError, setSystemOptionsError] = useState<string | null>(null)
  const [definition, setDefinition] = useState<ConnectionFormDefinition | null>(null)
  const [dialogState, setDialogState] = useState(EMPTY_DIALOG_STATE)
  const [connectionForm, setConnectionForm] = useState<ConnectionFormValues>({})
  const [persistedSecrets, setPersistedSecrets] = useState<ConnectionFormValues>({})
  const [parseWarnings, setParseWarnings] = useState<string[]>([])
  const [preview, setPreview] = useState<ConnectionPreviewResponse | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testFeedback, setTestFeedback] = useState<TestFeedback | null>(null)

  const visibleFields = useMemo(() => {
    if (!definition) return []
    return definition.fields.filter(field => isFieldVisible(field, connectionForm))
  }, [definition, connectionForm])

  const basicFields = visibleFields.filter(field => !field.advanced)
  const advancedFields = visibleFields.filter(field => field.advanced)

  const buildEffectiveConnectionForm = useCallback((): ConnectionFormValues => {
    if (!definition) return {}

    const payload: ConnectionFormValues = {}
    definition.fields.forEach(field => {
      if (!isFieldVisible(field, connectionForm)) return
      const currentValue = normalizeFieldValue(connectionForm[field.key]).trim()

      if (field.secret && !currentValue && persistedSecrets[field.key]) {
        payload[field.key] = persistedSecrets[field.key]
        return
      }

      if (currentValue) {
        payload[field.key] = currentValue
      }
    })
    return payload
  }, [definition, connectionForm, persistedSecrets])

  const getConnectionValidationErrors = useCallback((): string[] => {
    if (!definition) return ["连接表单尚未加载完成"]

    const errors: string[] = []
    definition.fields.forEach(field => {
      if (!isFieldVisible(field, connectionForm)) return

      const value = normalizeFieldValue(connectionForm[field.key]).trim()
      const hasPersistedSecret = field.secret && Boolean(persistedSecrets[field.key])
      if (field.required && !value && !hasPersistedSecret) {
        errors.push(`请填写${field.label}`)
      }
    })
    return errors
  }, [definition, connectionForm, persistedSecrets])

  const connectionValidationErrors = useMemo(() => {
    return getConnectionValidationErrors()
  }, [getConnectionValidationErrors])

  const effectiveConnectionForm = useMemo(() => {
    return buildEffectiveConnectionForm()
  }, [buildEffectiveConnectionForm])
  const selectedSystemOption = useMemo(
    () => systemOptions.find(option => option.system_short === dialogState.system_short),
    [systemOptions, dialogState.system_short]
  )

  const loadProfiles = useCallback(async (): Promise<DatabaseProfile[]> => {
    const response = await apiRequest(`${getApiUrl()}/api/text2sql/database-types`)
    if (!response.ok) {
      throw new Error("加载数据库类型失败")
    }
    return await response.json()
  }, [])

  const loadSystemOptions = useCallback(async (includeSystemShort?: string) => {
    try {
      const params = new URLSearchParams()
      if (includeSystemShort?.trim()) {
        params.set("include_system_short", includeSystemShort.trim())
      }
      const query = params.toString()
      const response = await apiRequest(
        `${getApiUrl()}/api/system-registry/options${query ? `?${query}` : ""}`
      )
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(getApiErrorMessage(payload, "加载系统选项失败"))
      }
      const payload = await response.json()
      const nextOptions = Array.isArray(payload?.data) ? payload.data : []
      setSystemOptions(nextOptions)
      setSystemOptionsError(null)
      return nextOptions as SystemOption[]
    } catch (error) {
      setSystemOptions([])
      setSystemOptionsError(error instanceof Error ? error.message : "加载系统选项失败")
      return []
    }
  }, [])

  const loadDefinition = useCallback(async (
    dbType: string,
    options?: {
      seedValues?: Record<string, unknown>
      persistedSecretSeed?: ConnectionFormValues
      warnings?: string[]
      keepAdvanced?: boolean
      previewPayload?: ConnectionPreviewResponse | null
    }
  ) => {
    const response = await apiRequest(`${getApiUrl()}/api/text2sql/database-types/${dbType}/connection-form`)
    if (!response.ok) {
      throw new Error("加载连接表单失败")
    }

    const nextDefinition = (await response.json()) as ConnectionFormDefinition
    setDefinition(nextDefinition)
    setConnectionForm(buildFormValues(nextDefinition, options?.seedValues))
    setPersistedSecrets(options?.persistedSecretSeed || {})
    setParseWarnings(options?.warnings || [])
    setPreview(options?.previewPayload || null)
    setPreviewError(null)
    setShowAdvanced(Boolean(options?.keepAdvanced))
    return nextDefinition
  }, [])

  const bootstrapCreateDialog = useCallback(async (loadedProfiles: DatabaseProfile[]) => {
    const defaultType = loadedProfiles[0]?.db_type || "mysql"
    setDialogState({
      name: "",
      system_short: "",
      database_name: "",
      env: "",
      type: defaultType,
      read_only: true,
    })
    await Promise.all([
      loadDefinition(defaultType),
      loadSystemOptions(),
    ])
  }, [loadDefinition, loadSystemOptions])

  const bootstrapEditDialog = useCallback(async () => {
    const detailResponse = await apiRequest(`${getApiUrl()}/api/text2sql/databases/${databaseId}`)
    if (!detailResponse.ok) {
      throw new Error("加载数据源详情失败")
    }

    const detail = (await detailResponse.json()) as DatabaseDetail
    setDialogState({
      name: detail.name,
      system_short: detail.system_short,
      database_name: detail.database_name ?? "",
      env: detail.env,
      type: detail.type,
      read_only: detail.read_only,
    })

    const [parseResponse, nextDefinition] = await Promise.all([
      apiRequest(`${getApiUrl()}/api/text2sql/connection/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          db_type: detail.type,
          connection_mode: "url",
          url: detail.url,
          read_only: detail.read_only,
        }),
      }),
      apiRequest(`${getApiUrl()}/api/text2sql/database-types/${detail.type}/connection-form`),
      loadSystemOptions(detail.system_short),
    ])

    if (!parseResponse.ok || !nextDefinition.ok) {
      throw new Error("加载数据源表单失败")
    }

    const parsedPayload = await parseResponse.json()
    const resolvedDefinition = (await nextDefinition.json()) as ConnectionFormDefinition
    const secretSeed = extractPersistedSecrets(resolvedDefinition, parsedPayload.form || {})
    const nextValues = buildFormValues(resolvedDefinition, parsedPayload.form || {})

    resolvedDefinition.fields.forEach(field => {
      if (field.secret && secretSeed[field.key]) {
        nextValues[field.key] = ""
      }
    })

    setDefinition(resolvedDefinition)
    setConnectionForm(nextValues)
    setPersistedSecrets(secretSeed)
    setParseWarnings(Array.isArray(parsedPayload.warnings) ? parsedPayload.warnings : [])
    setPreview(
      parsedPayload.masked_url
        ? {
            url: detail.url,
            masked_url: parsedPayload.masked_url,
            db_type: detail.type,
          }
        : null
    )
    setPreviewError(null)
    setShowAdvanced(hasAdvancedContent(resolvedDefinition, parsedPayload.form || {}))
  }, [databaseId, loadSystemOptions])

  useEffect(() => {
    if (!open) return

    let cancelled = false

    const bootstrap = async () => {
      setLoading(true)
      setDefinition(null)
      setConnectionForm({})
      setPersistedSecrets({})
      setParseWarnings([])
      setPreview(null)
      setPreviewError(null)
      setTestFeedback(null)
      setSystemOptions([])
      setSystemOptionsError(null)
      setShowAdvanced(false)

      try {
        const loadedProfiles = await loadProfiles()
        if (cancelled) return
        setProfiles(loadedProfiles)

        if (databaseId) {
          await bootstrapEditDialog()
        } else {
          await bootstrapCreateDialog(loadedProfiles)
        }
      } catch (error) {
        console.error(error)
        toast.error(error instanceof Error ? error.message : "加载数据源表单失败")
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void bootstrap()

    return () => {
      cancelled = true
    }
  }, [open, databaseId, loadProfiles, bootstrapCreateDialog, bootstrapEditDialog])

  useEffect(() => {
    if (!open || !definition || !dialogState.type) return

    if (connectionValidationErrors.length > 0) {
      setPreview(null)
      setPreviewError(null)
      return
    }

    let cancelled = false
    const timer = window.setTimeout(async () => {
      setPreviewLoading(true)
      try {
        const response = await apiRequest(`${getApiUrl()}/api/text2sql/connection/preview`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            db_type: dialogState.type,
            connection_mode: "form",
            connection_form: effectiveConnectionForm,
            read_only: dialogState.read_only,
          }),
        })

        if (!response.ok) {
          const data = await response.json().catch(() => ({}))
          if (!cancelled) {
            setPreview(null)
            setPreviewError(getApiErrorMessage(data, "生成连接串预览失败"))
          }
          return
        }

        const payload = (await response.json()) as ConnectionPreviewResponse
        if (!cancelled) {
          setPreview(payload)
          setPreviewError(null)
        }
      } catch (error) {
        console.error(error)
        if (!cancelled) {
          setPreview(null)
          setPreviewError("生成连接串预览失败")
        }
      } finally {
        if (!cancelled) {
          setPreviewLoading(false)
        }
      }
    }, 300)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [open, definition, dialogState.type, dialogState.read_only, connectionValidationErrors, effectiveConnectionForm])

  const handleTypeChange = async (nextType: string) => {
    setDialogState(current => ({ ...current, type: nextType }))
    setPreview(null)
    setPreviewError(null)
    setParseWarnings([])
    setTestFeedback(null)

    try {
      await loadDefinition(nextType)
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "切换数据库类型失败")
    }
  }

  const handleFieldChange = (fieldKey: string, nextValue: string) => {
    setTestFeedback(null)
    setConnectionForm(current => ({
      ...current,
      [fieldKey]: nextValue,
    }))
  }

  const handleTestConnection = async () => {
    if (connectionValidationErrors.length > 0) {
      toast.error(connectionValidationErrors[0])
      setTestFeedback({
        type: "error",
        message: connectionValidationErrors[0],
      })
      return
    }

    setTesting(true)
    setTestFeedback(null)
    try {
      const response = await apiRequest(`${getApiUrl()}/api/text2sql/connection/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          db_type: dialogState.type,
          connection_mode: "form",
          connection_form: effectiveConnectionForm,
          read_only: dialogState.read_only,
        }),
      })

      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        const message = getApiErrorMessage(payload, "连接测试失败")
        setTestFeedback({
          type: "error",
          message,
        })
        toast.error(message)
        return
      }

      if (payload.masked_url) {
        setPreview({
          url: payload.url,
          masked_url: payload.masked_url,
          db_type: payload.db_type,
        })
      }
      const message = payload.message || "连接测试成功"
      setTestFeedback({
        type: "success",
        message,
      })
      toast.success(message)
    } catch (error) {
      console.error(error)
      setTestFeedback({
        type: "error",
        message: "连接测试失败",
      })
      toast.error("连接测试失败")
    } finally {
      setTesting(false)
    }
  }

  const handleSubmit = async () => {
    if (!dialogState.name.trim()) {
      toast.error("请填写数据源名称")
      return
    }

    if (!dialogState.system_short.trim()) {
      toast.error("请填写所属系统")
      return
    }
    if (selectedSystemOption && selectedSystemOption.status !== "active") {
      toast.error("当前系统已停用，请选择一个有效系统")
      return
    }

    if (!dialogState.env.trim()) {
      toast.error("请填写环境标识")
      return
    }

    if (connectionValidationErrors.length > 0) {
      toast.error(connectionValidationErrors[0])
      return
    }

    setSubmitting(true)
    try {
      const requestPayload = {
        name: dialogState.name.trim(),
        system_short: dialogState.system_short.trim(),
        database_name: dialogState.database_name.trim() || undefined,
        env: dialogState.env.trim(),
        type: dialogState.type,
        connection_mode: "form",
        connection_form: effectiveConnectionForm,
        read_only: dialogState.read_only,
      }

      const requestUrl = databaseId
        ? `${getApiUrl()}/api/text2sql/databases/${databaseId}`
        : `${getApiUrl()}/api/text2sql/databases`

      const response = await apiRequest(requestUrl, {
        method: databaseId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestPayload),
      })

      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        toast.error(getApiErrorMessage(payload, "保存数据源失败"))
        return
      }

      toast.success(databaseId ? "数据源已更新" : "数据源已创建")
      onSuccess()
      onOpenChange(false)
    } catch (error) {
      console.error(error)
      toast.error("保存数据源失败")
    } finally {
      setSubmitting(false)
    }
  }

  const databaseTypeOptions: SelectOption[] = profiles.map(profile => ({
    value: profile.db_type,
    label: profile.display_name,
    description: `${profile.category} · ${profile.support_level}`,
  }))
  const systemShortOptions: SelectOption[] = systemOptions.map(system => ({
    value: system.system_short,
    label: `${system.system_short} · ${system.display_name}`,
    description: system.status === "active"
      ? (system.description || "可用于新建或更新数据源")
      : `当前系统状态：${system.status}${system.description ? ` · ${system.description}` : ""}`,
  }))

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[92vw] sm:max-w-3xl p-0 flex flex-col bg-background">
        <SheetHeader className="border-b px-6 py-4 pr-14 shrink-0">
          <SheetTitle>{databaseId ? "编辑 SQL 数据源" : "新增 SQL 数据源"}</SheetTitle>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="py-12 flex justify-center">
              <Loader2 className="w-6 h-6 animate-spin" />
            </div>
          ) : (
            <div className="grid gap-6 pb-2">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="grid gap-2">
                  <Label htmlFor="database-name">数据源名称</Label>
                  <Input
                    id="database-name"
                    value={dialogState.name}
                    onChange={event => setDialogState(current => ({ ...current, name: event.target.value }))}
                    placeholder="例如：订单分析库"
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="database-system-short">所属系统</Label>
                  {systemOptionsError ? (
                    <>
                      <Input
                        id="database-system-short"
                        value={dialogState.system_short}
                        onChange={event => setDialogState(current => ({ ...current, system_short: event.target.value }))}
                        placeholder="输入所属系统简称"
                      />
                      <div className="text-xs text-amber-600">
                        {systemOptionsError}，当前回退为手动输入。
                      </div>
                    </>
                  ) : (
                    <Select
                      value={dialogState.system_short}
                      onValueChange={value => setDialogState(current => ({ ...current, system_short: value }))}
                      options={systemShortOptions}
                      placeholder="选择所属系统"
                      disabled={loading || systemShortOptions.length === 0}
                    />
                  )}
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="database-env">环境</Label>
                  <Input
                    id="database-env"
                    value={dialogState.env}
                    onChange={event => setDialogState(current => ({ ...current, env: event.target.value }))}
                    placeholder="例如：prod / test / uat"
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="database-logical-name">逻辑数据库名</Label>
                  <Input
                    id="database-logical-name"
                    value={dialogState.database_name}
                    onChange={event =>
                      setDialogState(current => ({
                        ...current,
                        database_name: event.target.value,
                      }))
                    }
                    placeholder="例如：crm_core；留空则尝试自动识别"
                  />
                  <div className="text-xs text-muted-foreground">
                    跨环境复用要求 system_short 与 database_name 同时一致。
                  </div>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="database-type">数据库类型</Label>
                  <Select
                    value={dialogState.type}
                    onValueChange={handleTypeChange}
                    options={databaseTypeOptions}
                    placeholder="选择数据库类型"
                  />
                </div>
              </div>
              {definition && (
                <div className="rounded-xl border bg-card p-5">
                  <div className="mb-4 flex items-center justify-between gap-4">
                    <div>
                      <div className="text-sm font-semibold">连接信息</div>
                      <div className="text-sm text-muted-foreground">
                        按数据库类型填写结构化字段，系统会自动生成并保存连接字符串。
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Sparkles className="h-4 w-4" />
                      自动生成连接串
                    </div>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    {basicFields.map(field => {
                      const savedSecretHint = field.secret && persistedSecrets[field.key]
                      const value = normalizeFieldValue(connectionForm[field.key])
                      return (
                        <div key={field.key} className={field.input_type === "textarea" ? "md:col-span-2" : ""}>
                          <div className="grid gap-2">
                            <Label htmlFor={field.key}>
                              {field.label}
                              {field.required && <span className="ml-1 text-red-500">*</span>}
                            </Label>
                            {field.input_type === "select" ? (
                              <Select
                                value={value}
                                onValueChange={nextValue => handleFieldChange(field.key, nextValue)}
                                options={field.options.map(option => ({
                                  value: option.value,
                                  label: option.label,
                                }))}
                                placeholder={`请选择${field.label}`}
                              />
                            ) : field.input_type === "textarea" ? (
                              <Textarea
                                id={field.key}
                                value={value}
                                onChange={event => handleFieldChange(field.key, event.target.value)}
                                placeholder={field.placeholder || undefined}
                                className="min-h-[96px]"
                              />
                            ) : (
                              <Input
                                id={field.key}
                                type={field.input_type === "password" ? "password" : field.input_type === "number" ? "number" : "text"}
                                value={value}
                                onChange={event => handleFieldChange(field.key, event.target.value)}
                                placeholder={
                                  savedSecretHint
                                    ? "已保存，留空则保持不变"
                                    : field.placeholder || undefined
                                }
                                autoComplete={field.secret ? "new-password" : undefined}
                              />
                            )}
                            {savedSecretHint ? <div className="text-xs text-muted-foreground">密码已保存，只有在你输入新值时才会覆盖。</div> : null}
                            {field.description ? <div className="text-xs text-muted-foreground">{field.description}</div> : null}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                  {advancedFields.length > 0 && (
                    <div className="mt-5 border-t pt-5">
                      <button
                        type="button"
                        onClick={() => setShowAdvanced(current => !current)}
                        className="text-sm font-medium text-primary"
                      >
                        {showAdvanced ? "收起高级参数" : "展开高级参数"}
                      </button>
                      {showAdvanced && (
                        <div className="mt-4 grid gap-4 md:grid-cols-2">
                          {advancedFields.map(field => {
                            const savedSecretHint = field.secret && persistedSecrets[field.key]
                            const value = normalizeFieldValue(connectionForm[field.key])
                            return (
                              <div key={field.key} className={field.input_type === "textarea" ? "md:col-span-2" : ""}>
                                <div className="grid gap-2">
                                  <Label htmlFor={field.key}>
                                    {field.label}
                                    {field.required && <span className="ml-1 text-red-500">*</span>}
                                  </Label>
                                  {field.input_type === "select" ? (
                                    <Select
                                      value={value}
                                      onValueChange={nextValue => handleFieldChange(field.key, nextValue)}
                                      options={field.options.map(option => ({
                                        value: option.value,
                                        label: option.label,
                                      }))}
                                      placeholder={`请选择${field.label}`}
                                    />
                                  ) : field.input_type === "textarea" ? (
                                    <Textarea
                                      id={field.key}
                                      value={value}
                                      onChange={event => handleFieldChange(field.key, event.target.value)}
                                      placeholder={field.placeholder || undefined}
                                      className="min-h-[96px]"
                                    />
                                  ) : (
                                    <Input
                                      id={field.key}
                                      type={field.input_type === "password" ? "password" : field.input_type === "number" ? "number" : "text"}
                                      value={value}
                                      onChange={event => handleFieldChange(field.key, event.target.value)}
                                      placeholder={
                                        savedSecretHint
                                          ? "已保存，留空则保持不变"
                                          : field.placeholder || undefined
                                      }
                                      autoComplete={field.secret ? "new-password" : undefined}
                                    />
                                  )}
                                  {savedSecretHint ? <div className="text-xs text-muted-foreground">密码已保存，只有在你输入新值时才会覆盖。</div> : null}
                                  {field.description ? <div className="text-xs text-muted-foreground">{field.description}</div> : null}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
              <div className="flex items-center justify-between rounded-xl border bg-card p-4">
                <div className="space-y-0.5">
                  <Label htmlFor="read-only" className="flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4 text-emerald-600" />
                    只读模式
                  </Label>
                  <p className="text-xs text-muted-foreground">建议默认开启，避免误写库操作。</p>
                </div>
                <Switch
                  id="read-only"
                  checked={dialogState.read_only}
                  onCheckedChange={checked => setDialogState(current => ({ ...current, read_only: checked }))}
                />
              </div>
              {definition && (
                <div className="rounded-xl border bg-card p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-semibold">连接验证</div>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={handleTestConnection}
                      disabled={loading || submitting || testing || !definition}
                    >
                      {testing ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                      测试数据库连接
                    </Button>
                  </div>
                  {testFeedback ? (
                    <Alert className="mt-4" variant={testFeedback.type === "error" ? "destructive" : "default"}>
                      {testFeedback.type === "error" ? <AlertCircle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                      <AlertTitle>{testFeedback.type === "error" ? "连接失败" : "连接成功"}</AlertTitle>
                      <AlertDescription>{testFeedback.message}</AlertDescription>
                    </Alert>
                  ) : null}
                  {previewLoading ? (
                    <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      正在生成连接串预览...
                    </div>
                  ) : preview ? (
                    <div className="mt-4 rounded-lg bg-muted p-3 font-mono text-sm break-all">
                      {preview.masked_url}
                    </div>
                  ) : null}
                  {previewError ? <div className="mt-3 text-sm text-red-500">{previewError}</div> : null}
                  {parseWarnings.length > 0 && (
                    <div className="mt-3 space-y-1">
                      {parseWarnings.map(warning => (
                        <div key={warning} className="text-xs text-amber-600">
                          {warning}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
        <SheetFooter className="border-t px-6 py-4 shrink-0 sm:flex-row sm:justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting || testing}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={loading || submitting || testing || !definition}>
            {submitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
            {databaseId ? "保存" : "创建"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
