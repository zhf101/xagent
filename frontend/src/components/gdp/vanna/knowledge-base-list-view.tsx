"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import {
  Database,
  Loader2,
  Plus,
  RefreshCw,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { SearchInput } from "@/components/ui/search-input"
import {
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Select as SelectRadix,
} from "@/components/ui/select-radix"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn, formatDate } from "@/lib/utils"

import {
  createVannaKnowledgeBase,
  listAskRuns,
  listSchemaTables,
  listText2SqlDatabases,
  listTrainingEntries,
  listVannaKnowledgeBases,
} from "./vanna-api"
import type {
  Text2SqlDatabaseRecord,
  VannaAskRunRecord,
  VannaKnowledgeBaseRecord,
  VannaSchemaTableRecord,
  VannaTrainingEntryRecord,
} from "./vanna-types"

function getKbStatusTone(status: string) {
  if (status === "active") {
    return "bg-emerald-500/10 text-emerald-600 border-emerald-200"
  }
  if (status === "draft") {
    return "bg-amber-500/10 text-amber-600 border-amber-200"
  }
  return "bg-zinc-500/10 text-zinc-600 border-zinc-200"
}

function formatDateOrFallback(value?: string | null) {
  return value ? formatDate(value) : "暂无"
}

export function KnowledgeBaseListView() {
  const router = useRouter()

  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [creatingDatasourceId, setCreatingDatasourceId] = useState<number | null>(null)
  const [searchTerm, setSearchTerm] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [knowledgeBases, setKnowledgeBases] = useState<VannaKnowledgeBaseRecord[]>([])
  const [datasources, setDatasources] = useState<Text2SqlDatabaseRecord[]>([])
  const [schemaTables, setSchemaTables] = useState<VannaSchemaTableRecord[]>([])
  const [entries, setEntries] = useState<VannaTrainingEntryRecord[]>([])
  const [askRuns, setAskRuns] = useState<VannaAskRunRecord[]>([])

  async function loadData(showRefreshState: boolean) {
    if (showRefreshState) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }

    try {
      const [kbRows, datasourceRows, tableRows, entryRows, askRunRows] = await Promise.all([
        listVannaKnowledgeBases(),
        listText2SqlDatabases(),
        listSchemaTables({}),
        listTrainingEntries({}),
        listAskRuns({}),
      ])
      setKnowledgeBases(kbRows)
      setDatasources(datasourceRows)
      setSchemaTables(tableRows)
      setEntries(entryRows)
      setAskRuns(askRunRows)
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "知识库列表加载失败")
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    void loadData(false)
  }, [])

  const tableCountByKb = schemaTables.reduce<Record<number, number>>((acc, row) => {
    if (row.status === "active") {
      acc[row.kb_id] = (acc[row.kb_id] ?? 0) + 1
    }
    return acc
  }, {})

  const publishedEntryCountByKb = entries.reduce<Record<number, number>>((acc, row) => {
    if (row.lifecycle_status === "published") {
      acc[row.kb_id] = (acc[row.kb_id] ?? 0) + 1
    }
    return acc
  }, {})

  const candidateEntryCountByKb = entries.reduce<Record<number, number>>((acc, row) => {
    if (row.lifecycle_status === "candidate") {
      acc[row.kb_id] = (acc[row.kb_id] ?? 0) + 1
    }
    return acc
  }, {})

  const askRunCountByKb = askRuns.reduce<Record<number, number>>((acc, row) => {
    acc[row.kb_id] = (acc[row.kb_id] ?? 0) + 1
    return acc
  }, {})

  const datasourceIdsWithKb = new Set(knowledgeBases.map(item => item.datasource_id))
  const creatableDatasources = datasources.filter(item => !datasourceIdsWithKb.has(item.id))

  const filteredKnowledgeBases = knowledgeBases.filter(item => {
    const matchesStatus = statusFilter === "all" || item.status === statusFilter
    const keyword = searchTerm.trim().toLowerCase()
    const matchesKeyword =
      keyword.length === 0 ||
      item.name.toLowerCase().includes(keyword) ||
      item.kb_code.toLowerCase().includes(keyword) ||
      item.system_short.toLowerCase().includes(keyword) ||
      (item.database_name || "").toLowerCase().includes(keyword) ||
      item.env.toLowerCase().includes(keyword)
    return matchesStatus && matchesKeyword
  })

  async function handleCreateKnowledgeBase(datasource: Text2SqlDatabaseRecord) {
    setCreatingDatasourceId(datasource.id)
    try {
      const kb = await createVannaKnowledgeBase({
        datasource_id: datasource.id,
        name: `${datasource.name} 知识库`,
        description: `${datasource.system_short}/${datasource.database_name || "-"}/${datasource.env} 数据源默认知识库`,
      })
      toast.success("默认知识库已创建")
      await loadData(true)
      router.push(`/knowledge-bases/${kb.id}/facts`)
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "创建知识库失败")
    } finally {
      setCreatingDatasourceId(null)
    }
  }

  if (loading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-zinc-50/50 text-foreground">
      <header className="flex h-16 shrink-0 items-center justify-between border-b bg-background px-8 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-primary p-2 shadow-sm">
            <Database className="h-5 w-5 text-primary-foreground" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight">知识库中心</h1>
            <p className="text-xs text-muted-foreground">
              管理 Vanna 训练知识、结构事实和 ask 运行资产
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="outline" onClick={() => router.push("/sql/datasources")}>
            <Plus className="mr-2 h-4 w-4" />
            数据源管理
          </Button>
          <Button
            variant="secondary"
            onClick={() => void loadData(true)}
            disabled={refreshing}
          >
            {refreshing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-2 h-4 w-4" />
            )}
            刷新
          </Button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto p-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-6">
          <div className="flex flex-wrap items-center gap-4 rounded-[2rem] border bg-card p-5 shadow-sm">
            <SearchInput
              value={searchTerm}
              onChange={setSearchTerm}
              placeholder="搜索知识库名称、编码、系统简称或环境"
              className="h-10 w-80 rounded-xl"
            />
            <SelectRadix value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-10 w-36 rounded-xl bg-background">
                <SelectValue placeholder="状态" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="draft">Draft</SelectItem>
                <SelectItem value="archived">Archived</SelectItem>
              </SelectContent>
            </SelectRadix>
          </div>

          {creatableDatasources.length > 0 ? (
            <section className="rounded-[2rem] border bg-card p-6 shadow-sm">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-black tracking-tight">可创建默认知识库的数据源</h2>
                  <p className="text-sm text-muted-foreground">
                    Vanna 知识库与数据源一一绑定，每个数据源最多创建一个默认知识库。
                  </p>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {creatableDatasources.map(item => (
                  <div key={item.id} className="rounded-2xl border bg-background p-5">
                    <div className="mb-4 flex items-start justify-between gap-3">
                      <div>
                        <h3 className="text-base font-bold">{item.name}</h3>
                        <div className="mt-1 flex items-center gap-2 text-xs font-mono text-muted-foreground">
                          <span>{item.system_short}</span>
                          <span className="h-1 w-1 rounded-full bg-border" />
                          <span>{item.database_name || "-"}</span>
                          <span className="h-1 w-1 rounded-full bg-border" />
                          <span>{item.env}</span>
                          <span className="h-1 w-1 rounded-full bg-border" />
                          <span>{item.type}</span>
                        </div>
                      </div>
                      <Badge variant="outline">{item.status}</Badge>
                    </div>
                    <div className="mb-4 text-xs text-muted-foreground">
                      识别表数 {item.table_count ?? 0}
                    </div>
                    <Button
                      className="w-full"
                      onClick={() => void handleCreateKnowledgeBase(item)}
                      disabled={creatingDatasourceId === item.id}
                    >
                      {creatingDatasourceId === item.id ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Plus className="mr-2 h-4 w-4" />
                      )}
                      创建默认知识库
                    </Button>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section className="space-y-4">
            <div className="flex items-center justify-between px-1">
              <h2 className="text-lg font-black tracking-tight">知识库列表</h2>
              <span className="text-xs font-bold text-muted-foreground">
                共 {filteredKnowledgeBases.length} 个知识库
              </span>
            </div>
            <div className="overflow-hidden rounded-[2rem] border bg-card shadow-sm">
              <Table>
                <TableHeader>
                  <TableRow className="bg-zinc-50/80 hover:bg-zinc-50/80">
                    <TableHead className="min-w-[220px]">知识库</TableHead>
                    <TableHead className="w-[110px]">状态</TableHead>
                    <TableHead className="w-[220px]">系统 / 数据库 / 环境</TableHead>
                    <TableHead className="min-w-[180px]">数据源</TableHead>
                    <TableHead className="w-[110px]">活跃表数</TableHead>
                    <TableHead className="w-[120px]">已发布知识</TableHead>
                    <TableHead className="w-[100px]">待审核</TableHead>
                    <TableHead className="w-[100px]">Ask 记录</TableHead>
                    <TableHead className="w-[170px]">最后训练</TableHead>
                    <TableHead className="w-[170px]">最后 Ask</TableHead>
                    <TableHead className="w-[120px] text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredKnowledgeBases.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={11} className="py-16 text-center text-muted-foreground">
                        还没有可展示的知识库。先配置数据源，再为数据源创建默认知识库。
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredKnowledgeBases.map(item => (
                      <TableRow
                        key={item.id}
                        className="cursor-pointer"
                        onClick={() => router.push(`/knowledge-bases/${item.id}/facts`)}
                      >
                        <TableCell>
                          <div className="space-y-1">
                            <div className="font-semibold">{item.name}</div>
                            <div className="font-mono text-xs text-muted-foreground">{item.kb_code}</div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={getKbStatusTone(item.status)}>
                            {item.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="space-y-1 text-sm">
                            <div className="font-medium">{item.system_short}</div>
                            <div className="text-xs text-muted-foreground">
                              {item.database_name || "-"} / {item.env}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="space-y-1 text-sm">
                            <div className="font-medium">{item.datasource_name || `#${item.datasource_id}`}</div>
                            <div className="text-xs text-muted-foreground">ID: {item.datasource_id}</div>
                          </div>
                        </TableCell>
                        <TableCell>{tableCountByKb[item.id] ?? 0}</TableCell>
                        <TableCell>{publishedEntryCountByKb[item.id] ?? 0}</TableCell>
                        <TableCell>
                          <span className={cn(
                            "font-medium",
                            (candidateEntryCountByKb[item.id] ?? 0) > 0 && "text-amber-600"
                          )}>
                            {candidateEntryCountByKb[item.id] ?? 0}
                          </span>
                        </TableCell>
                        <TableCell>{askRunCountByKb[item.id] ?? 0}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatDateOrFallback(item.last_train_at)}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatDateOrFallback(item.last_ask_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(event) => {
                              event.stopPropagation()
                              router.push(`/knowledge-bases/${item.id}/facts`)
                            }}
                          >
                            查看表结构
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}

