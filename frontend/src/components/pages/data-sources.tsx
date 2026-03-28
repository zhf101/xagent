"use client"

import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import {
  Copy,
  Eye,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  Wrench,
  Trash2,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Select, type SelectOption } from "@/components/ui/select"
import { SearchInput } from "@/components/ui/search-input"
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
import { useI18n } from "@/contexts/i18n-context"
import {
  DataSourceConfigDialog,
  type DataSourceSavePayload,
} from "@/components/pages/data-source-config-dialog"

type DatabaseStatus = "connected" | "disconnected" | "error"

interface DatabaseRecord {
  id: number
  name: string
  system_id?: number | null
  system_short?: string | null
  system_name?: string | null
  type: string
  url: string
  read_only: boolean
  enabled: boolean
  status: DatabaseStatus
  table_count?: number | null
  last_connected_at?: string | null
  error_message?: string | null
  created_at: string
  updated_at: string
}

interface DatabaseTypeProfile {
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

interface BizSystemRecord {
  id: number
  system_short: string
  system_name: string
}

function formatDate(value?: string | null) {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function getStatusTone(status: DatabaseStatus) {
  if (status === "connected") return "border-green-500/30 bg-green-500/10 text-green-600"
  if (status === "error") return "border-red-500/30 bg-red-500/10 text-red-600"
  return "border-border bg-white text-muted-foreground"
}

function getEnabledTone(enabled: boolean) {
  return enabled
    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600"
    : "border-amber-500/30 bg-amber-500/10 text-amber-700"
}

export function DataSourcesPage() {
  const { t } = useI18n()
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [creatingSystem, setCreatingSystem] = useState(false)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [togglingId, setTogglingId] = useState<number | null>(null)
  const [databases, setDatabases] = useState<DatabaseRecord[]>([])
  const [profiles, setProfiles] = useState<DatabaseTypeProfile[]>([])
  const [systems, setSystems] = useState<BizSystemRecord[]>([])
  const [search, setSearch] = useState("")
  const [selectedSystemFilter, setSelectedSystemFilter] = useState("all")
  const [editingRecord, setEditingRecord] = useState<DatabaseRecord | null>(null)
  const [viewingRecord, setViewingRecord] = useState<DatabaseRecord | null>(null)
  const [isFormDialogOpen, setIsFormDialogOpen] = useState(false)
  const [isSystemDialogOpen, setIsSystemDialogOpen] = useState(false)
  const [systemForm, setSystemForm] = useState({ system_short: "", system_name: "" })

  const loadAll = async () => {
    setLoading(true)
    try {
      const dbRes = await apiRequest(`${getApiUrl()}/api/text2sql/databases`, { headers: {} })
      if (dbRes.ok) {
        setDatabases(await dbRes.json())
      } else {
        const detail = await dbRes.json().catch(() => ({}))
        toast.error(detail.detail || "数据源列表加载失败")
        setDatabases([])
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载数据源失败")
      setDatabases([])
    } finally {
      setLoading(false)
    }

    void (async () => {
      try {
        const profileRes = await apiRequest(`${getApiUrl()}/api/text2sql/database-types`, { headers: {} })
        if (!profileRes.ok) {
          const detail = await profileRes.json().catch(() => ({}))
          toast.error(detail.detail || "数据库类型模板加载失败")
          setProfiles([])
          return
        }
        const profilePayload = await profileRes.json()
        setProfiles(profilePayload)
      } catch {
        toast.error("数据库类型模板加载失败")
        setProfiles([])
      }
    })()

    void (async () => {
      try {
        const systemRes = await apiRequest(`${getApiUrl()}/api/text2sql/systems`, { headers: {} })
        if (!systemRes.ok) {
          const detail = await systemRes.json().catch(() => ({}))
          toast.error(detail.detail || "业务系统列表加载失败，请先执行数据库迁移")
          setSystems([])
          return
        }
        const systemPayload = await systemRes.json()
        setSystems(systemPayload)
      } catch {
        toast.error("业务系统列表加载失败，请先执行数据库迁移")
        setSystems([])
      }
    })()
  }

  useEffect(() => {
    void loadAll()
  }, [])

  const filteredDatabases = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    return databases.filter((item) =>
      (selectedSystemFilter === "all" ||
        String(item.system_id || "") === selectedSystemFilter) &&
      (!keyword ||
        [item.name, item.type, item.url, item.system_short || "", item.system_name || ""]
          .some((field) => field.toLowerCase().includes(keyword)))
    )
  }, [databases, search, selectedSystemFilter])

  const systemFilterOptions: SelectOption[] = useMemo(
    () => [
      {
        value: "all",
        label: "全部系统",
        description: "不过滤业务系统",
      },
      ...systems.map((item) => ({
        value: String(item.id),
        label: item.system_name,
        description: item.system_short,
      })),
    ],
    [systems]
  )

  const handleSaveDataSource = async (payload: DataSourceSavePayload) => {
    setSubmitting(true)
    try {
      const url = editingRecord
        ? `${getApiUrl()}/api/text2sql/databases/${editingRecord.id}`
        : `${getApiUrl()}/api/text2sql/databases`

      const response = await apiRequest(url, {
        method: editingRecord ? "PUT" : "POST",
        headers: {},
        body: JSON.stringify({
          ...payload,
        }),
      })

      const responsePayload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(responsePayload.detail || "保存数据源失败")
      }

      setIsFormDialogOpen(false)
      setEditingRecord(null)
      await loadAll()
      toast.success(editingRecord ? "数据源已更新" : "数据源已创建")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存数据源失败")
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (record: DatabaseRecord) => {
    if (!confirm(`确定要删除数据源“${record.name}”吗？`)) return
    try {
      const response = await apiRequest(
        `${getApiUrl()}/api/text2sql/databases/${record.id}`,
        { method: "DELETE", headers: {} }
      )
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || "删除数据源失败")
      }
      await loadAll()
      toast.success("数据源已删除")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除数据源失败")
    }
  }

  const handleToggleEnabled = async (record: DatabaseRecord) => {
    setTogglingId(record.id)
    try {
      const response = await apiRequest(
        `${getApiUrl()}/api/text2sql/databases/${record.id}/toggle-enabled`,
        { method: "POST", headers: {} }
      )
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || "切换启用状态失败")
      }
      await loadAll()
      toast.success(payload.enabled ? "数据源已启用" : "数据源已禁用")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "切换启用状态失败")
    } finally {
      setTogglingId(null)
    }
  }

  const handleCopy = async (record: DatabaseRecord) => {
    try {
      await navigator.clipboard.writeText(record.url)
      toast.success("连接字符串已复制")
    } catch {
      toast.error("复制失败")
    }
  }

  const handleTest = async (record: DatabaseRecord) => {
    setTestingId(record.id)
    try {
      const response = await apiRequest(
        `${getApiUrl()}/api/text2sql/databases/${record.id}/test`,
        { method: "POST", headers: {} }
      )
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || "连接测试失败")
      }
      await loadAll()
      toast.success(payload.message || "连接测试成功")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "连接测试失败")
    } finally {
      setTestingId(null)
    }
  }

  const handleCreateSystem = async () => {
    if (!systemForm.system_short.trim() || !systemForm.system_name.trim()) {
      toast.error("请填写系统简称和系统名称")
      return
    }
    setCreatingSystem(true)
    try {
      const response = await apiRequest(`${getApiUrl()}/api/text2sql/systems`, {
        method: "POST",
        headers: {},
        body: JSON.stringify(systemForm),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || "创建业务系统失败")
      }
      setSystems((prev) => [...prev, payload].sort((a, b) => a.system_short.localeCompare(b.system_short)))
      setSystemForm({ system_short: "", system_name: "" })
      setIsSystemDialogOpen(false)
      toast.success("业务系统已创建")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "创建业务系统失败")
    } finally {
      setCreatingSystem(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="border-b border-border/80 px-6 py-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg border border-border/60 bg-primary/5 px-2.5 py-1 text-xs font-medium text-primary">
              DATA SOURCE
            </div>
            <h1 className="text-xl font-semibold tracking-tight">数据源配置</h1>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => void loadAll()} disabled={loading}>
              <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              刷新
            </Button>
            <Button variant="outline" onClick={() => setIsSystemDialogOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              新增系统
            </Button>
            <Button onClick={() => {
              setEditingRecord(null)
              setIsFormDialogOpen(true)
            }}>
              <Plus className="mr-2 h-4 w-4" />
              新增数据源
            </Button>
          </div>
        </div>
      </div>

      <div className="p-6">
        <Card className="overflow-hidden border-border/80 py-0 shadow-none">
          <CardHeader className="gap-3 border-b border-border/80 py-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center gap-2">
                <CardTitle className="text-base">数据源列表</CardTitle>
                <Badge variant="outline" className="h-6 rounded-md px-2 text-xs">
                  {filteredDatabases.length}
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
                    placeholder="搜索数据源..."
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
                    <TableHead>类型</TableHead>
                    <TableHead>连接模式</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>最近连通</TableHead>
                    <TableHead className="w-[300px]">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {loading ? (
                    <TableRow>
                      <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                        加载中...
                      </TableCell>
                    </TableRow>
                  ) : filteredDatabases.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                        暂无数据源
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredDatabases.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="py-3">
                          <div className="font-medium">{item.name}</div>
                          <div className="max-w-[240px] truncate text-[11px] text-muted-foreground">{item.url}</div>
                        </TableCell>
                        <TableCell className="py-3">
                          <div>{item.system_name || "未绑定系统"}</div>
                          <div className="text-[11px] text-muted-foreground">{item.system_short || "-"}</div>
                        </TableCell>
                        <TableCell className="py-3">
                          <Badge variant="outline" className="rounded-md text-[11px]">
                            {item.type}
                          </Badge>
                        </TableCell>
                        <TableCell className="py-3 text-sm">{item.read_only ? "只读" : "读写"}</TableCell>
                        <TableCell className="py-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="outline" className={`rounded-md text-[11px] ${getStatusTone(item.status)}`}>
                              {item.status}
                            </Badge>
                            <Badge variant="outline" className={`rounded-md text-[11px] ${getEnabledTone(item.enabled)}`}>
                              {item.enabled ? "enabled" : "disabled"}
                            </Badge>
                          </div>
                        </TableCell>
                        <TableCell className="py-3 text-sm text-muted-foreground">
                          {formatDate(item.last_connected_at)}
                        </TableCell>
                        <TableCell className="py-3">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button size="sm" variant="outline" className="h-8 rounded-md px-2.5" onClick={() => setViewingRecord(item)}>
                                  <Eye className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>查看详情</TooltipContent>
                            </Tooltip>

                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button size="sm" variant="outline" className="h-8 rounded-md px-2.5" onClick={() => {
                                  setEditingRecord(item)
                                  setIsFormDialogOpen(true)
                                }}>
                                  <Pencil className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>编辑数据源</TooltipContent>
                            </Tooltip>

                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className={`h-8 rounded-md px-2.5 ${item.enabled ? "text-amber-700" : "text-emerald-700"}`}
                                  onClick={() => handleToggleEnabled(item)}
                                  disabled={togglingId === item.id}
                                >
                                  <Power className={`h-3.5 w-3.5 ${togglingId === item.id ? "animate-pulse" : ""}`} />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>{item.enabled ? "禁用数据源" : "启用数据源"}</TooltipContent>
                            </Tooltip>

                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button size="sm" variant="outline" className="h-8 rounded-md px-2.5" onClick={() => handleCopy(item)}>
                                  <Copy className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>复制连接字符串</TooltipContent>
                            </Tooltip>

                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-8 rounded-md px-2.5"
                                  onClick={() => handleTest(item)}
                                  disabled={testingId === item.id || !item.enabled}
                                >
                                  <Wrench className={`h-3.5 w-3.5 ${testingId === item.id ? "animate-spin" : ""}`} />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>{item.enabled ? "测试连接" : "数据源已禁用，无法测试"}</TooltipContent>
                            </Tooltip>

                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button size="sm" variant="outline" className="h-8 rounded-md px-2.5 text-red-600" onClick={() => handleDelete(item)}>
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>删除数据源</TooltipContent>
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

      <DataSourceConfigDialog
        open={isFormDialogOpen}
        editingRecord={editingRecord}
        systems={systems}
        profiles={profiles}
        submitting={submitting}
        onOpenChange={setIsFormDialogOpen}
        onCreateSystem={() => setIsSystemDialogOpen(true)}
        onSubmit={handleSaveDataSource}
      />

      <Dialog open={!!viewingRecord} onOpenChange={(open) => !open && setViewingRecord(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>查看数据源</DialogTitle>
            <DialogDescription>查看当前数据源的业务归属、连接信息和接入模板。</DialogDescription>
          </DialogHeader>
          {viewingRecord ? (
            <div className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-xl border border-border bg-white p-4">
                  <div className="text-xs text-muted-foreground">业务系统</div>
                  <div className="mt-1 font-medium">{viewingRecord.system_name || "未绑定系统"}</div>
                  <div className="text-xs text-muted-foreground">{viewingRecord.system_short || "-"}</div>
                </div>
                <div className="rounded-xl border border-border bg-white p-4">
                  <div className="text-xs text-muted-foreground">数据库类型</div>
                  <div className="mt-1 font-medium">{viewingRecord.type}</div>
                </div>
              </div>
              <div className="rounded-xl border border-border bg-white p-4">
                <div className="text-xs text-muted-foreground">连接字符串</div>
                <div className="mt-2 break-all text-sm">{viewingRecord.url}</div>
              </div>
              {profiles
                .filter((item) => item.db_type === viewingRecord.type)
                .map((profile) => (
                  <div key={profile.db_type} className="space-y-3 rounded-xl border border-border p-4">
                    <div className="flex flex-wrap gap-2">
                      <Badge variant="outline">{profile.display_name}</Badge>
                      <Badge variant="outline">{profile.protocol}</Badge>
                      <Badge variant="outline">{profile.support_level}</Badge>
                    </div>
                    <div className="text-xs text-muted-foreground">连接模板</div>
                    <div className="rounded-lg border border-border bg-white p-3 text-xs break-all">
                      {profile.connection_example}
                    </div>
                    <div className="text-xs text-muted-foreground">驱动依赖</div>
                    <div className="flex flex-wrap gap-2">
                      {profile.driver_packages.length > 0 ? (
                        profile.driver_packages.map((driver) => (
                          <Badge key={driver} variant="outline">{driver}</Badge>
                        ))
                      ) : (
                        <Badge variant="outline">无需额外驱动</Badge>
                      )}
                    </div>
                  </div>
                ))}
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setViewingRecord(null)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={isSystemDialogOpen} onOpenChange={setIsSystemDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>新增业务系统</DialogTitle>
            <DialogDescription>先维护业务系统主数据，再把数据源绑定到系统。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="system-short">系统简称</Label>
              <Input
                id="system-short"
                value={systemForm.system_short}
                onChange={(event) =>
                  setSystemForm((prev) => ({ ...prev, system_short: event.target.value }))
                }
                placeholder="例如：crm"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="system-name">系统名称</Label>
              <Input
                id="system-name"
                value={systemForm.system_name}
                onChange={(event) =>
                  setSystemForm((prev) => ({ ...prev, system_name: event.target.value }))
                }
                placeholder="例如：客户关系管理系统"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsSystemDialogOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={handleCreateSystem} disabled={creatingSystem}>
              {creatingSystem ? t("common.loading") : t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
