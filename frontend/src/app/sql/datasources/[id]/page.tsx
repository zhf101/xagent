"use client"

import React, { useCallback, useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { ArrowLeft, Database, Loader2, Play } from "lucide-react"
import { getApiUrl } from "@/lib/utils"
import { apiRequest } from "@/lib/api-wrapper"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"

interface DatabaseDetail {
  id: number
  name: string
  type: string
  url?: string
  read_only: boolean
  status?: string
  table_count?: number
  last_connected_at?: string | null
  error_message?: string | null
}

export default function SqlDataSourceDetailPage() {
  const params = useParams()
  const router = useRouter()
  const id = params.id as string

  const [dbInfo, setDbInfo] = useState<DatabaseDetail | null>(null)
  const [loading, setLoading] = useState(true)
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
          <Button variant="secondary" onClick={handleTestConnection} disabled={testingConnection}>
            {testingConnection ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
            测试连接
          </Button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto w-full p-8">
        <div className="max-w-5xl mx-auto">
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-card border rounded-xl p-5 shadow-sm">
                <div className="text-sm text-muted-foreground mb-1">数据库类型</div>
                <div className="text-xl font-bold uppercase">{dbInfo.type}</div>
              </div>
              <div className="bg-card border rounded-xl p-5 shadow-sm">
                <div className="text-sm text-muted-foreground mb-1">识别表数量</div>
                <div className="text-xl font-bold">{dbInfo.table_count ?? "-"}</div>
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
                  <div className="col-span-3 text-sm">{dbInfo.last_connected_at ? new Date(dbInfo.last_connected_at).toLocaleString() : "从不"}</div>
                </div>
                {dbInfo.error_message && (
                  <div className="grid grid-cols-4 gap-4">
                    <div className="text-sm text-red-500">连接错误</div>
                    <div className="col-span-3 text-sm text-red-500 bg-red-500/10 p-3 rounded">{dbInfo.error_message}</div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
