"use client"

import React, { useEffect, useState } from "react"
import { Plus, Link2 } from "lucide-react"
import { getApiUrl } from "@/lib/utils"
import { apiRequest } from "@/lib/api-wrapper"
import { Button } from "@/components/ui/button"
import { HttpConfigDrawer } from "./http-config-drawer"

export function HttpAssetsPageView() {
  const [httpAssets, setHttpAssets] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [isHttpDrawerOpen, setIsHttpDrawerOpen] = useState(false)
  const [editingHttpId, setEditingHttpId] = useState<number | undefined>(undefined)

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await apiRequest(`${getApiUrl()}/api/v1/gdp/http-assets`)
      if (res.ok) {
        setHttpAssets((await res.json()).data || [])
      }
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleEditHttpAsset = (id: number) => {
    setEditingHttpId(id)
    setIsHttpDrawerOpen(true)
  }

  const handleCreateHttpAsset = () => {
    setEditingHttpId(undefined)
    setIsHttpDrawerOpen(true)
  }

  return (
    <div className="flex flex-col h-screen w-full bg-background overflow-hidden text-foreground">
      <header className="h-16 bg-background border-b border-border flex items-center justify-between px-8 shrink-0 shadow-sm z-10">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-primary rounded-lg shadow-sm">
            <Link2 className="w-5 h-5 text-primary-foreground" />
          </div>
          <h1 className="text-xl font-bold tracking-tight">GDP HTTP 接口资产</h1>
        </div>
        <Button onClick={handleCreateHttpAsset} className="flex items-center gap-2">
          <Plus className="w-4 h-4" />
          新建接口
        </Button>
      </header>

      <main className="flex-1 overflow-y-auto w-full p-8">
        <div className="max-w-6xl mx-auto">
          <div className="mb-6">
            <h2 className="text-sm font-bold text-muted-foreground uppercase tracking-wider mb-2">接口资源管理 (GDP 分层协议)</h2>
            <p className="text-muted-foreground text-sm">注册并管理面向 GDP 召回与 MCP 工具调用的 HTTP 接口资产。新协议支持三层分层设计。</p>
          </div>

          {loading && httpAssets.length === 0 ? (
            <div className="flex justify-center py-20">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
            </div>
          ) : httpAssets.length === 0 ? (
            <div className="bg-card border border-border rounded-xl p-16 flex flex-col items-center justify-center text-center shadow-sm">
              <div className="w-16 h-16 bg-secondary/50 rounded-full flex items-center justify-center mb-4">
                <Link2 className="w-8 h-8 text-muted-foreground/60" />
              </div>
              <h3 className="text-lg font-bold">暂无 HTTP 接口</h3>
              <p className="text-muted-foreground mt-2 max-w-xs">点击右上角按钮注册您的第一个 GDP 接口资产。</p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {httpAssets.map(asset => (
                <div 
                  key={asset.id} 
                  onClick={() => handleEditHttpAsset(asset.id)}
                  className="group bg-card border border-border rounded-xl p-5 hover:border-primary/40 hover:shadow-md transition-all cursor-pointer"
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="w-10 h-10 rounded-full bg-primary/10 text-primary flex items-center justify-center group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
                      <Link2 className="w-5 h-5" />
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-secondary font-mono text-muted-foreground tracking-wider uppercase font-bold">
                        {asset.resource_key}
                      </span>
                      {asset.system_short && (
                        <span className="text-[9px] text-muted-foreground/60 font-medium">系统: {asset.system_short}</span>
                      )}
                    </div>
                  </div>
                  <h4 className="font-bold group-hover:text-primary transition-colors line-clamp-1 mb-2">
                    {asset.tool_name}
                  </h4>
                  <p className="text-xs text-muted-foreground line-clamp-2 min-h-[2rem]">
                    {asset.tool_description || "暂无描述"}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      <HttpConfigDrawer 
        open={isHttpDrawerOpen}
        onOpenChange={setIsHttpDrawerOpen}
        onSaved={loadData}
        assetId={editingHttpId}
      />
    </div>
  )
}
