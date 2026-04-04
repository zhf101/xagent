"use client"

import React, { useCallback, useEffect, useMemo, useState } from "react"
import { Check, ClipboardList, RefreshCw, X } from "lucide-react"

import { apiRequest } from "@/lib/api-wrapper"
import { getApiErrorMessage } from "@/lib/api-errors"
import { getApiUrl } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { SearchInput } from "@/components/ui/search-input"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { toast } from "sonner"

type AssetChangeRequestItem = {
  id: number
  request_type: string
  asset_type: string
  asset_id?: string | null
  system_short: string
  env?: string | null
  status: string
  requested_by: number
  requested_at?: string | null
  submitted_at?: string | null
  approved_at?: string | null
  rejected_at?: string | null
  reject_reason?: string | null
  change_summary?: string | null
}

type ViewMode = "queue" | "mine"

function formatTimestamp(value?: string | null): string {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function getStatusBadgeVariant(status: string): "default" | "destructive" | "outline" | "secondary" {
  switch (status) {
    case "approved":
      return "default"
    case "rejected":
    case "cancelled":
    case "superseded":
      return "destructive"
    case "pending_approval":
      return "secondary"
    default:
      return "outline"
  }
}

export default function ApprovalQueuePage() {
  const [viewMode, setViewMode] = useState<ViewMode>("queue")
  const [loading, setLoading] = useState(true)
  const [actingId, setActingId] = useState<number | null>(null)
  const [keyword, setKeyword] = useState("")
  const [queueItems, setQueueItems] = useState<AssetChangeRequestItem[]>([])
  const [myItems, setMyItems] = useState<AssetChangeRequestItem[]>([])

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [queueResponse, myResponse] = await Promise.all([
        apiRequest(`${getApiUrl()}/api/approval-queue`),
        apiRequest(`${getApiUrl()}/api/asset-change-requests/my`),
      ])

      if (queueResponse.ok) {
        const payload = await queueResponse.json()
        setQueueItems(payload.data || [])
      } else {
        const error = await queueResponse.json().catch(() => null)
        toast.error(getApiErrorMessage(error, "加载审批队列失败"))
      }

      if (myResponse.ok) {
        const payload = await myResponse.json()
        setMyItems(payload.data || [])
      } else {
        const error = await myResponse.json().catch(() => null)
        toast.error(getApiErrorMessage(error, "加载我的申请失败"))
      }
    } catch (error) {
      console.error(error)
      toast.error("加载审批数据失败")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const visibleItems = useMemo(() => {
    const source = viewMode === "queue" ? queueItems : myItems
    const search = keyword.trim().toLowerCase()
    if (!search) return source

    return source.filter(item => {
      return [
        item.system_short,
        item.env,
        item.asset_type,
        item.request_type,
        item.change_summary,
        String(item.id),
      ]
        .filter(Boolean)
        .some(value => String(value).toLowerCase().includes(search))
    })
  }, [keyword, myItems, queueItems, viewMode])

  const submitAction = useCallback(
    async (requestId: number, action: "approve" | "reject" | "cancel") => {
      if (action === "approve" && !window.confirm(`确认通过审批单 #${requestId} 吗？`)) {
        return
      }
      if (action === "cancel" && !window.confirm(`确认撤回审批单 #${requestId} 吗？`)) {
        return
      }

      let body: string | undefined
      if (action === "reject") {
        const reason = window.prompt("请输入拒绝原因", "")
        if (reason === null) {
          return
        }
        body = JSON.stringify({ reason })
      } else if (action === "approve") {
        body = JSON.stringify({ comment: "approved in web console" })
      }

      setActingId(requestId)
      try {
        const response = await apiRequest(
          `${getApiUrl()}/api/asset-change-requests/${requestId}/${action}`,
          {
            method: "POST",
            headers: body ? { "Content-Type": "application/json" } : undefined,
            body,
          }
        )

        if (!response.ok) {
          const error = await response.json().catch(() => null)
          toast.error(getApiErrorMessage(error, `审批操作失败: ${action}`))
          return
        }

        toast.success(
          action === "approve"
            ? "审批已通过"
            : action === "reject"
              ? "审批已拒绝"
              : "申请已撤回"
        )
        await loadData()
      } catch (error) {
        console.error(error)
        toast.error("审批操作失败")
      } finally {
        setActingId(null)
      }
    },
    [loadData]
  )

  return (
    <div className="flex flex-col h-screen w-full bg-background overflow-hidden text-foreground">
      <header className="h-16 bg-background border-b border-border flex items-center justify-between px-8 shrink-0 shadow-sm z-10">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-emerald-500 rounded-lg shadow-sm">
            <ClipboardList className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight">资产审批队列</h1>
            <p className="text-xs text-muted-foreground">按 system_short 处理资产创建、更新、删除审批</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <SearchInput
            value={keyword}
            onChange={setKeyword}
            placeholder="搜索系统、类型、摘要或审批单号"
            className="w-80"
          />
          <Button variant="outline" onClick={loadData} disabled={loading}>
            <RefreshCw className="w-4 h-4 mr-2" />
            刷新
          </Button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto w-full p-8">
        <div className="max-w-7xl mx-auto space-y-6">
          <div className="flex items-center gap-3">
            <Button
              variant={viewMode === "queue" ? "default" : "outline"}
              onClick={() => setViewMode("queue")}
            >
              待我审批
              <Badge variant="secondary" className="ml-2">
                {queueItems.length}
              </Badge>
            </Button>
            <Button
              variant={viewMode === "mine" ? "default" : "outline"}
              onClick={() => setViewMode("mine")}
            >
              我的申请
              <Badge variant="secondary" className="ml-2">
                {myItems.length}
              </Badge>
            </Button>
          </div>

          <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[100px]">审批单</TableHead>
                  <TableHead className="w-[120px]">系统</TableHead>
                  <TableHead className="w-[120px]">资产类型</TableHead>
                  <TableHead className="w-[110px]">变更类型</TableHead>
                  <TableHead className="w-[100px]">环境</TableHead>
                  <TableHead>变更摘要</TableHead>
                  <TableHead className="w-[140px]">状态</TableHead>
                  <TableHead className="w-[190px]">提交时间</TableHead>
                  <TableHead className="w-[220px] text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  <TableRow>
                    <TableCell colSpan={9} className="py-16 text-center text-muted-foreground">
                      正在加载审批数据...
                    </TableCell>
                  </TableRow>
                ) : visibleItems.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} className="py-16 text-center text-muted-foreground">
                      {viewMode === "queue" ? "当前没有待审批申请" : "当前没有申请记录"}
                    </TableCell>
                  </TableRow>
                ) : (
                  visibleItems.map(item => {
                    const isActing = actingId === item.id
                    return (
                      <TableRow key={item.id}>
                        <TableCell className="font-mono text-xs">#{item.id}</TableCell>
                        <TableCell className="font-medium">{item.system_short}</TableCell>
                        <TableCell>{item.asset_type}</TableCell>
                        <TableCell>{item.request_type}</TableCell>
                        <TableCell>{item.env || "-"}</TableCell>
                        <TableCell className="max-w-[420px]">
                          <div className="line-clamp-2">{item.change_summary || "-"}</div>
                          {item.reject_reason ? (
                            <div className="text-xs text-red-500 mt-1">拒绝原因: {item.reject_reason}</div>
                          ) : null}
                        </TableCell>
                        <TableCell>
                          <Badge variant={getStatusBadgeVariant(item.status)}>{item.status}</Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatTimestamp(item.submitted_at || item.requested_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-2">
                            {viewMode === "queue" ? (
                              <>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  disabled={isActing || item.status !== "pending_approval"}
                                  onClick={() => void submitAction(item.id, "reject")}
                                >
                                  <X className="w-4 h-4 mr-1" />
                                  拒绝
                                </Button>
                                <Button
                                  size="sm"
                                  disabled={isActing || item.status !== "pending_approval"}
                                  onClick={() => void submitAction(item.id, "approve")}
                                >
                                  <Check className="w-4 h-4 mr-1" />
                                  通过
                                </Button>
                              </>
                            ) : (
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={isActing || item.status !== "pending_approval"}
                                onClick={() => void submitAction(item.id, "cancel")}
                              >
                                撤回
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </div>
      </main>
    </div>
  )
}
