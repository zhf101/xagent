"use client"

import React, { useEffect, useState, useMemo } from "react"
import { Plus, Link2, Search, ChevronLeft, ChevronRight, Edit2, Trash2, Globe, Lock, Users } from "lucide-react"
import { getApiUrl, cn } from "@/lib/utils"
import { apiRequest } from "@/lib/api-wrapper"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { HttpConfigDrawer } from "./http-config-drawer"
import { SearchInput } from "@/components/ui/search-input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"

interface HttpAssetRow {
  id: number
  tool_name?: string
  resource_key?: string
  system_short?: string
  tool_description?: string
  method?: string
  visibility?: string
}

export function HttpAssetsPageView() {
  const [httpAssets, setHttpAssets] = useState<HttpAssetRow[]>([])
  const [loading, setLoading] = useState(true)
  const [isHttpDrawerOpen, setIsHttpDrawerOpen] = useState(false)
  const [editingHttpId, setEditingHttpId] = useState<number | undefined>(undefined)

  // 批量选择状态
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [isDeleting, setIsDeleting] = useState(false)

  // 搜索和分页状态
  const [searchTerm, setSearchTerm] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const pageSize = 10

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

  // 删除单条资产
  const handleDeleteAsset = async (id: number) => {
    if (!confirm("确定要删除该接口资产吗？")) return
    try {
      const res = await apiRequest(`${getApiUrl()}/api/v1/gdp/http-assets/${id}`, { method: "DELETE" })
      if (res.ok) {
        // 删除成功后刷新列表，并清除选中状态中的该 id
        setSelectedIds(prev => { const s = new Set(prev); s.delete(id); return s })
        await loadData()
      }
    } catch (err) {
      console.error(err)
    }
  }

  // 批量删除：逐条调用单条删除接口（后端暂无批量删除接口）
  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return
    if (!confirm(`确定要删除选中的 ${selectedIds.size} 条接口资产吗？`)) return
    setIsDeleting(true)
    try {
      await Promise.all(
        Array.from(selectedIds).map(id =>
          apiRequest(`${getApiUrl()}/api/v1/gdp/http-assets/${id}`, { method: "DELETE" })
        )
      )
      setSelectedIds(new Set())
      await loadData()
    } catch (err) {
      console.error(err)
    } finally {
      setIsDeleting(false)
    }
  }

  // 切换单行选中
  const toggleSelect = (id: number) => {
    setSelectedIds(prev => {
      const s = new Set(prev)
      if (s.has(id)) {
        s.delete(id)
      } else {
        s.add(id)
      }
      return s
    })
  }

  // 过滤逻辑
  const filteredAssets = useMemo(() => {
    return httpAssets.filter(asset => {
      const search = searchTerm.toLowerCase()
      return (
        asset.tool_name?.toLowerCase().includes(search) ||
        asset.resource_key?.toLowerCase().includes(search) ||
        asset.system_short?.toLowerCase().includes(search) ||
        asset.tool_description?.toLowerCase().includes(search)
      )
    })
  }, [httpAssets, searchTerm])

  // 分页逻辑
  const totalPages = Math.ceil(filteredAssets.length / pageSize)
  const paginatedAssets = useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return filteredAssets.slice(start, start + pageSize)
  }, [filteredAssets, currentPage])

  // 重置分页
  useEffect(() => {
    setCurrentPage(1)
  }, [searchTerm])

  // 当前页全选 / 取消全选（依赖 paginatedAssets，必须在其后定义）
  const isAllCurrentPageSelected =
    paginatedAssets.length > 0 && paginatedAssets.every(a => selectedIds.has(a.id))

  const toggleSelectAll = () => {
    if (isAllCurrentPageSelected) {
      setSelectedIds(prev => {
        const s = new Set(prev)
        paginatedAssets.forEach(a => s.delete(a.id))
        return s
      })
    } else {
      setSelectedIds(prev => {
        const s = new Set(prev)
        paginatedAssets.forEach(a => s.add(a.id))
        return s
      })
    }
  }

  const getVisibilityIcon = (visibility: string) => {
    switch (visibility) {
      case "global": return <Globe className="w-3 h-3" />
      case "shared": return <Users className="w-3 h-3" />
      default: return <Lock className="w-3 h-3" />
    }
  }

  const getMethodColor = (method: string) => {
    switch (method?.toUpperCase()) {
      case "GET": return "bg-blue-500/10 text-blue-600 border-blue-200"
      case "POST": return "bg-green-500/10 text-green-600 border-green-200"
      case "PUT": return "bg-amber-500/10 text-amber-600 border-amber-200"
      case "DELETE": return "bg-red-500/10 text-red-600 border-red-200"
      default: return "bg-secondary text-secondary-foreground"
    }
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
        <div className="flex items-center gap-4">
          <SearchInput 
            placeholder="搜索工具名、资源键或系统..." 
            value={searchTerm} 
            onChange={setSearchTerm}
            className="w-64"
          />
          {selectedIds.size > 0 && (
            <Button
              variant="destructive"
              onClick={handleBatchDelete}
              disabled={isDeleting}
              className="flex items-center gap-2"
            >
              <Trash2 className="w-4 h-4" />
              {isDeleting ? "删除中..." : `批量删除 (${selectedIds.size})`}
            </Button>
          )}
          <Button onClick={handleCreateHttpAsset} className="flex items-center gap-2">
            <Plus className="w-4 h-4" />
            新建接口
          </Button>
        </div>
      </header>

      <main className="flex-1 overflow-hidden w-full flex flex-col p-8">
        <div className="max-w-7xl mx-auto w-full flex flex-col h-full">
          <div className="flex-1 min-h-0 bg-card border border-border rounded-xl shadow-sm overflow-hidden flex flex-col">
            <div className="flex-1 overflow-auto">
              {loading && httpAssets.length === 0 ? (
                <div className="flex justify-center py-20">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                </div>
              ) : filteredAssets.length === 0 ? (
                <div className="p-16 flex flex-col items-center justify-center text-center">
                  <div className="w-16 h-16 bg-secondary/50 rounded-full flex items-center justify-center mb-4">
                    <Search className="w-8 h-8 text-muted-foreground/60" />
                  </div>
                  <h3 className="text-lg font-bold">{searchTerm ? "未找到匹配的接口" : "暂无 HTTP 接口"}</h3>
                  <p className="text-muted-foreground mt-2 max-w-xs">
                    {searchTerm ? "尝试调整搜索关键词" : "点击右上角按钮注册您的第一个 GDP 接口资产。"}
                  </p>
                </div>
              ) : (
                <Table>
                  <TableHeader className="sticky top-0 bg-card z-10">
                    <TableRow>
                      {/* 全选 checkbox */}
                      <TableHead className="w-[44px]">
                        <Checkbox
                          checked={isAllCurrentPageSelected}
                          onCheckedChange={toggleSelectAll}
                        />
                      </TableHead>
                      <TableHead className="w-[80px]">ID</TableHead>
                      <TableHead className="min-w-[200px]">工具名称</TableHead>
                      <TableHead className="w-[120px]">系统</TableHead>
                      <TableHead className="w-[100px]">方法</TableHead>
                      <TableHead className="max-w-[300px]">描述</TableHead>
                      <TableHead className="w-[120px]">可见性</TableHead>
                      <TableHead className="w-[120px] text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {paginatedAssets.map(asset => (
                      <TableRow
                        key={asset.id}
                        className="group hover:bg-muted/30 transition-colors cursor-pointer"
                        data-state={selectedIds.has(asset.id) ? "selected" : undefined}
                        onDoubleClick={() => handleEditHttpAsset(asset.id)}
                      >
                        <TableCell>
                          <Checkbox
                            checked={selectedIds.has(asset.id)}
                            onCheckedChange={() => toggleSelect(asset.id)}
                          />
                        </TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">#{asset.id}</TableCell>
                        <TableCell className="font-bold">{asset.tool_name}</TableCell>
                        <TableCell>
                          <span className="text-sm font-medium">{asset.system_short || "-"}</span>
                        </TableCell>
                        <TableCell>
                          <Badge 
                            variant="outline" 
                            className={cn("font-bold px-2 py-0 text-[10px]", getMethodColor(asset.method || "POST"))}
                          >
                            {asset.method || "POST"}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <p className="text-xs text-muted-foreground line-clamp-1" title={asset.tool_description}>
                            {asset.tool_description || "-"}
                          </p>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            {getVisibilityIcon(asset.visibility || "private")}
                            <span className="capitalize">{asset.visibility || "private"}</span>
                          </div>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            {/* 查看/编辑 */}
                            <Button 
                              variant="ghost" 
                              size="icon" 
                              onClick={() => handleEditHttpAsset(asset.id)}
                              className="h-8 w-8"
                              title="查看"
                            >
                              <Edit2 className="h-4 w-4" />
                            </Button>
                            {/* 删除 */}
                            <Button 
                              variant="ghost" 
                              size="icon" 
                              onClick={() => handleDeleteAsset(asset.id)}
                              className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10"
                              title="删除"
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>

            {/* 分页条 */}
            {!loading && filteredAssets.length > 0 && (
              <div className="h-14 border-t border-border px-6 flex items-center justify-between bg-muted/20 shrink-0">
                <div className="text-xs text-muted-foreground">
                  共 <span className="font-bold text-foreground">{filteredAssets.length}</span> 条数据
                  {searchTerm && <span> (从 {httpAssets.length} 条中筛选)</span>}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground mr-2">
                    第 {currentPage} / {totalPages || 1} 页
                  </span>
                  <Button 
                    variant="outline" 
                    size="icon" 
                    className="h-8 w-8" 
                    disabled={currentPage === 1}
                    onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <Button 
                    variant="outline" 
                    size="icon" 
                    className="h-8 w-8" 
                    disabled={currentPage >= totalPages}
                    onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
          </div>
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
