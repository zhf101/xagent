"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import {
  Activity,
  ArrowRight,
  BookOpen,
  Database,
  Loader2,
  Plus,
  RefreshCw,
  Sparkles,
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

function isRecent(value?: string | null) {
  if (!value) {
    return false
  }
  const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000
  return new Date(value).getTime() >= sevenDaysAgo
}

function getKbStatusTone(status: string) {
  if (status === "active") {
    return "bg-emerald-500/10 text-emerald-600 border-emerald-200"
  }
  if (status === "draft") {
    return "bg-amber-500/10 text-amber-600 border-amber-200"
  }
  return "bg-zinc-500/10 text-zinc-600 border-zinc-200"
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
      item.env.toLowerCase().includes(keyword)
    return matchesStatus && matchesKeyword
  })

  async function handleCreateKnowledgeBase(datasource: Text2SqlDatabaseRecord) {
    setCreatingDatasourceId(datasource.id)
    try {
      const kb = await createVannaKnowledgeBase({
        datasource_id: datasource.id,
        name: `${datasource.name} 知识库`,
        description: `${datasource.system_short}/${datasource.env} 数据源默认知识库`,
      })
      toast.success("默认知识库已创建")
      await loadData(true)
      router.push(`/knowledge-bases/${kb.id}`)
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
        <div className="mx-auto flex max-w-7xl flex-col gap-8">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-6">
            {[
              { label: "知识库总数", value: knowledgeBases.length, icon: Database, tone: "text-sky-600" },
              {
                label: "Active",
                value: knowledgeBases.filter(item => item.status === "active").length,
                icon: Activity,
                tone: "text-emerald-600",
              },
              {
                label: "Draft",
                value: knowledgeBases.filter(item => item.status === "draft").length,
                icon: BookOpen,
                tone: "text-amber-600",
              },
              {
                label: "近 7 天训练活跃",
                value: knowledgeBases.filter(item => isRecent(item.last_train_at)).length,
                icon: Sparkles,
                tone: "text-violet-600",
              },
              {
                label: "近 7 天 Ask 活跃",
                value: knowledgeBases.filter(item => isRecent(item.last_ask_at)).length,
                icon: Activity,
                tone: "text-indigo-600",
              },
              {
                label: "待创建默认知识库",
                value: creatableDatasources.length,
                icon: Plus,
                tone: "text-zinc-600",
              },
            ].map(item => (
              <div key={item.label} className="rounded-2xl border bg-card p-5 shadow-sm">
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                    {item.label}
                  </span>
                  <item.icon className={cn("h-4 w-4", item.tone)} />
                </div>
                <div className="text-3xl font-black">{item.value}</div>
              </div>
            ))}
          </div>

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
                          <span>{item.env}</span>
                          <span className="h-1 w-1 rounded-full bg-border" />
                          <span>{item.type}</span>
                        </div>
                      </div>
                      <Badge variant="outline">{item.status}</Badge>
                    </div>
                    <div className="mb-4 text-xs text-muted-foreground">
                      识别表数 {item.table_count ?? 0}，已关联 SQL 资产 {item.linked_asset_count ?? 0}
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

            {filteredKnowledgeBases.length === 0 ? (
              <div className="rounded-[2rem] border border-dashed bg-card p-12 text-center shadow-sm">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                  <Database className="h-6 w-6 text-primary" />
                </div>
                <h3 className="text-lg font-bold">还没有可展示的知识库</h3>
                <p className="mt-2 text-sm text-muted-foreground">
                  先配置数据源，再为数据源创建默认知识库，即可进入训练和治理流程。
                </p>
              </div>
            ) : (
              <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
                {filteredKnowledgeBases.map(item => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => router.push(`/knowledge-bases/${item.id}`)}
                    className="group flex flex-col rounded-[2rem] border bg-card p-6 text-left shadow-sm transition-all hover:border-primary/30 hover:shadow-xl"
                  >
                    <div className="mb-4 flex items-start justify-between gap-3">
                      <div>
                        <div className="mb-2 flex items-center gap-2">
                          <h3 className="text-lg font-bold group-hover:text-primary">
                            {item.name}
                          </h3>
                          <Badge variant="outline" className={getKbStatusTone(item.status)}>
                            {item.status}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-2 text-xs font-mono text-muted-foreground">
                          <span>{item.kb_code}</span>
                          <span className="h-1 w-1 rounded-full bg-border" />
                          <span>{item.system_short}</span>
                          <span className="h-1 w-1 rounded-full bg-border" />
                          <span>{item.env}</span>
                        </div>
                      </div>
                    </div>

                    <div className="my-4 grid grid-cols-2 gap-4 border-y border-dashed border-border/60 py-5">
                      <div>
                        <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                          活跃表数
                        </div>
                        <div className="text-sm font-medium">
                          <span className="font-black text-foreground">
                            {tableCountByKb[item.id] ?? 0}
                          </span>
                          <span className="text-muted-foreground"> 张</span>
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                          已发布知识
                        </div>
                        <div className="text-sm font-medium">
                          <span className="font-black text-foreground">
                            {publishedEntryCountByKb[item.id] ?? 0}
                          </span>
                          <span className="text-muted-foreground"> 条</span>
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                          待审核
                        </div>
                        <div className="text-sm font-medium text-amber-600">
                          {candidateEntryCountByKb[item.id] ?? 0} 条
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                          Ask 记录
                        </div>
                        <div className="text-sm font-medium">
                          <span className="font-black text-foreground">
                            {askRunCountByKb[item.id] ?? 0}
                          </span>
                          <span className="text-muted-foreground"> 次</span>
                        </div>
                      </div>
                    </div>

                    <div className="mb-5 space-y-1 text-xs text-muted-foreground">
                      <div>数据源：{item.datasource_name || `#${item.datasource_id}`}</div>
                      <div>
                        最后训练：
                        {item.last_train_at ? formatDate(item.last_train_at) : "暂无"}
                      </div>
                      <div>
                        最后 Ask：
                        {item.last_ask_at ? formatDate(item.last_ask_at) : "暂无"}
                      </div>
                    </div>

                    <div className="mt-auto flex items-center justify-between text-sm font-bold text-primary">
                      <span>进入工作台</span>
                      <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  )
}

