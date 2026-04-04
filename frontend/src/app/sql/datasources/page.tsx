"use client"

import React, { useCallback, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Database, Plus, ChevronRight, Loader2, RefreshCw, Settings } from "lucide-react"
import { getApiUrl } from "@/lib/utils"
import { apiRequest } from "@/lib/api-wrapper"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"
import { SearchInput } from "@/components/ui/search-input"
import { DatabaseFormDialog } from "@/components/datamake/database-form-dialog"

interface DatabaseProfile {
  db_type: string
  display_name: string
}

interface SqlDatabaseItem {
  id: number
  name: string
  type: string
  read_only: boolean
  status?: string
  table_count?: number
  linked_asset_count?: number
  last_connected_at?: string | null
}

export default function SqlDataSourcesPage() {
  const [databases, setDatabases] = useState<SqlDatabaseItem[]>([])
  const [profileMap, setProfileMap] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState("")
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | undefined>(undefined)
  const router = useRouter()

  const loadDatabases = useCallback(async () => {
    setLoading(true)
    try {
      const [databasesResponse, profilesResponse] = await Promise.all([
        apiRequest(`${getApiUrl()}/api/text2sql/databases`),
        apiRequest(`${getApiUrl()}/api/text2sql/database-types`),
      ])

      if (databasesResponse.ok) {
        setDatabases(await databasesResponse.json())
      }
      if (profilesResponse.ok) {
        const profiles = (await profilesResponse.json()) as DatabaseProfile[]
        setProfileMap(
          profiles.reduce<Record<string, string>>((acc, profile) => {
            acc[profile.db_type] = profile.display_name
            return acc
          }, {})
        )
      }
    } catch (err) {
      console.error(err)
      toast.error("Failed to load data sources")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadDatabases()
  }, [loadDatabases])

  const handleCreate = () => {
    setEditingId(undefined)
    setIsFormOpen(true)
  }

  const handleEdit = (id: number) => {
    setEditingId(id)
    setIsFormOpen(true)
  }

  const filteredDatabases = databases.filter(db => {
    const profileName = profileMap[db.type] || db.type || ""
    const keyword = searchQuery.toLowerCase()
    return (
      db.name?.toLowerCase().includes(keyword) ||
      db.type?.toLowerCase().includes(keyword) ||
      profileName.toLowerCase().includes(keyword)
    )
  })

  return (
    <div className="flex flex-col h-screen w-full bg-background overflow-hidden text-foreground">
      <header className="h-16 bg-background border-b border-border flex items-center justify-between px-8 shrink-0 shadow-sm z-10">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-500 rounded-lg shadow-sm">
            <Database className="w-5 h-5 text-white" />
          </div>
          <h1 className="text-xl font-bold tracking-tight">SQL 数据源</h1>
        </div>
        <div className="flex items-center gap-4">
          <Button variant="outline" onClick={loadDatabases}>
            <RefreshCw className="w-4 h-4 mr-2" />
            刷新
          </Button>
          <Button onClick={handleCreate}>
            <Plus className="w-4 h-4 mr-2" />
            新增数据源
          </Button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto w-full p-8">
        <div className="max-w-6xl mx-auto">
          <div className="mb-6 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-bold text-foreground">数据源管理</h2>
              <p className="text-muted-foreground text-sm">统一管理结构化数据库连接并查看基础连通状态。</p>
            </div>
            <div className="w-72">
              <SearchInput 
                placeholder="搜索数据源..." 
                value={searchQuery}
                onChange={setSearchQuery}
              />
            </div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-8 h-8 animate-spin text-primary" />
            </div>
          ) : filteredDatabases.length === 0 ? (
            <div className="bg-card border border-border rounded-xl p-16 flex flex-col items-center justify-center text-center shadow-sm">
              <div className="w-16 h-16 bg-secondary/50 rounded-full flex items-center justify-center mb-4">
                <Database className="w-8 h-8 text-muted-foreground/60" />
              </div>
              <h3 className="text-lg font-bold">暂无 SQL 数据源</h3>
              <p className="text-muted-foreground mt-2 max-w-xs mb-6">您还没有配置任何数据库连接，请先添加数据源以便进行查询和资产沉淀。</p>
              <Button onClick={handleCreate}>添加数据源</Button>
            </div>
          ) : (
            <div className="grid gap-4">
              {filteredDatabases.map(db => (
                <div 
                  key={db.id} 
                  className="group bg-card border border-border rounded-xl p-5 hover:border-primary/40 hover:shadow-md transition-all flex items-center justify-between cursor-pointer"
                  onClick={() => router.push(`/sql/datasources/${db.id}`)}
                >
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-lg bg-indigo-500/10 text-indigo-500 flex items-center justify-center shrink-0">
                      <Database className="w-5 h-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <h4 className="font-bold group-hover:text-primary transition-colors">
                          {db.name}
                        </h4>
                        <span className="text-[10px] px-2 py-0.5 rounded bg-muted font-mono uppercase">
                          {profileMap[db.type] || db.type}
                        </span>
                        {db.read_only && (
                          <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-600 font-bold">
                            只读
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-4 text-xs text-muted-foreground">
                        <div className="flex items-center gap-1">
                          <span className="inline-block w-2 h-2 rounded-full" 
                            style={{ 
                              backgroundColor: db.status === 'connected' ? '#22c55e' : db.status === 'error' ? '#ef4444' : '#94a3b8' 
                            }} 
                          />
                          {db.status === 'connected' ? '连通' : db.status === 'error' ? '错误' : '未连接'}
                        </div>
                        {db.table_count !== undefined && (
                          <div>表数量: {db.table_count}</div>
                        )}
                        <div>关联资产: {db.linked_asset_count || 0}</div>
                        {db.last_connected_at && (
                          <div>最后连接: {new Date(db.last_connected_at).toLocaleString()}</div>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={event => {
                        event.stopPropagation()
                        handleEdit(db.id)
                      }}
                    >
                      <Settings className="w-4 h-4 mr-1" />
                      编辑
                    </Button>
                    <ChevronRight className="w-5 h-5 text-muted-foreground/50 group-hover:text-primary transform group-hover:translate-x-1 transition-all" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      <DatabaseFormDialog
        open={isFormOpen}
        onOpenChange={setIsFormOpen}
        databaseId={editingId}
        onSuccess={loadDatabases}
      />
    </div>
  )
}
