"use client"

import React, { useCallback, useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { ArrowLeft, Database, Plus, Loader2, Box, Settings, Play } from "lucide-react"
import { getApiUrl } from "@/lib/utils"
import { apiRequest } from "@/lib/api-wrapper"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { DatabaseFormDialog } from "@/components/datamake/database-form-dialog"

interface DatabaseDetail {
  id: number
  name: string
  type: string
  url?: string
  read_only: boolean
  status?: string
  table_count?: number
  linked_asset_count?: number
  last_connected_at?: string | null
  error_message?: string | null
}

export default function SqlDataSourceDetailPage() {
  const params = useParams()
  const router = useRouter()
  const id = params.id as string

  const [dbInfo, setDbInfo] = useState<DatabaseDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [testingConnection, setTestingConnection] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiRequest(`${getApiUrl()}/api/text2sql/databases/${id}`)
      if (res.ok) {
        setDbInfo(await res.json())
      } else {
        toast.error("数据源不存在或无权访问")
        router.push('/sql/datasources')
      }
    } catch (error) {
      console.error(error)
      toast.error("加载数据源失败")
    } finally {
      setLoading(false)
    }
  }, [id, router])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const handleTestConnection = async () => {
    setTestingConnection(true)
    try {
      const res = await apiRequest(`${getApiUrl()}/api/text2sql/databases/${id}/test`, {
        method: 'POST'
      })
      if (res.ok) {
        toast.success("连接测试成功！")
        loadData()
      } else {
        const data = await res.json()
        toast.error(`连接失败: ${data.detail || "未知错误"}`)
      }
    } catch {
      toast.error("测试请求失败")
    } finally {
      setTestingConnection(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    )
  }

  if (!dbInfo) return null

  return (
    <div className="flex flex-col h-screen w-full bg-background overflow-hidden text-foreground">
      <header className="h-16 bg-background border-b border-border flex items-center px-6 shrink-0 shadow-sm z-10">
        <Button variant="ghost" size="icon" className="mr-4" onClick={() => router.push('/sql/datasources')}>
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <div className="flex items-center gap-3 flex-1">
          <div className="p-2 bg-indigo-500/10 text-indigo-500 rounded-lg shadow-sm">
            <Database className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight leading-none">{dbInfo.name}</h1>
            <div className="flex items-center gap-2 mt-1 text-[11px] text-muted-foreground">
              <span className="uppercase font-mono bg-muted px-1 rounded">{dbInfo.type}</span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-1.5 h-1.5 rounded-full" 
                  style={{ backgroundColor: dbInfo.status === 'connected' ? '#22c55e' : dbInfo.status === 'error' ? '#ef4444' : '#94a3b8' }} 
                />
                {dbInfo.status}
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => setIsFormOpen(true)}>
            <Settings className="w-4 h-4 mr-2" /> 编辑配置
          </Button>
          <Button variant="secondary" onClick={handleTestConnection} disabled={testingConnection}>
            {testingConnection ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
            测试连接
          </Button>
          <Button onClick={() => router.push(`/sql/datasources/${id}/harvest`)}>
            <Plus className="w-4 h-4 mr-2" /> 采集资产
          </Button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto w-full p-8">
        <div className="max-w-5xl mx-auto">
          <Tabs defaultValue="overview">
            <TabsList className="mb-6">
              <TabsTrigger value="overview">数据源概览</TabsTrigger>
              <TabsTrigger value="assets">已采集资产</TabsTrigger>
            </TabsList>
            
            <TabsContent value="overview" className="space-y-6">
              <div className="grid grid-cols-3 gap-4">
                <div className="bg-card border rounded-xl p-5 shadow-sm">
                  <div className="text-sm text-muted-foreground mb-1">数据库类型</div>
                  <div className="text-xl font-bold uppercase">{dbInfo.type}</div>
                </div>
                <div className="bg-card border rounded-xl p-5 shadow-sm">
                  <div className="text-sm text-muted-foreground mb-1">识别表数量</div>
                  <div className="text-xl font-bold">{dbInfo.table_count ?? '-'}</div>
                </div>
                <div className="bg-card border rounded-xl p-5 shadow-sm">
                  <div className="text-sm text-muted-foreground mb-1">关联资产数</div>
                  <div className="text-xl font-bold">{dbInfo.linked_asset_count || 0}</div>
                </div>
              </div>

              <div className="bg-card border rounded-xl p-6 shadow-sm">
                <h3 className="text-sm font-bold uppercase text-muted-foreground mb-4">连接详情</h3>
                <div className="space-y-4">
                  <div className="grid grid-cols-4 gap-4 pb-4 border-b">
                    <div className="text-sm text-muted-foreground">URL</div>
                    <div className="col-span-3 text-sm font-mono break-all">{dbInfo.url}</div>
                  </div>
                  <div className="grid grid-cols-4 gap-4 pb-4 border-b">
                    <div className="text-sm text-muted-foreground">只读模式</div>
                    <div className="col-span-3 text-sm">{dbInfo.read_only ? "已开启" : "未开启"}</div>
                  </div>
                  <div className="grid grid-cols-4 gap-4 pb-4 border-b">
                    <div className="text-sm text-muted-foreground">最后连接时间</div>
                    <div className="col-span-3 text-sm">{dbInfo.last_connected_at ? new Date(dbInfo.last_connected_at).toLocaleString() : '从不'}</div>
                  </div>
                  {dbInfo.error_message && (
                    <div className="grid grid-cols-4 gap-4">
                      <div className="text-sm text-red-500">连接错误</div>
                      <div className="col-span-3 text-sm text-red-500 bg-red-500/10 p-3 rounded">{dbInfo.error_message}</div>
                    </div>
                  )}
                </div>
              </div>
            </TabsContent>

            <TabsContent value="assets">
              <div className="bg-card border rounded-xl p-16 flex flex-col items-center justify-center text-center shadow-sm">
                <Box className="w-12 h-12 text-muted-foreground/40 mb-4" />
                <h3 className="text-lg font-bold">查看关联资产</h3>
                <p className="text-muted-foreground mt-2 max-w-sm mb-6">
                  在此查看所有从当前数据源采集并注册的表结构、枚举、知识等受控资产。
                </p>
                <Button onClick={() => router.push(`/sql/assets/datasources/${id}`)}>
                  前往资产中心
                </Button>
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </main>

      <DatabaseFormDialog 
        open={isFormOpen}
        onOpenChange={setIsFormOpen}
        databaseId={parseInt(id)}
        onSuccess={loadData}
      />
    </div>
  )
}
