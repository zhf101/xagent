"use client"

import React, { useEffect, useMemo, useState } from "react"
import { useParams } from "next/navigation"
import {
  Edit2,
  Eye,
  Loader2,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { cn, formatDate } from "@/lib/utils"

import {
  archiveVannaSqlAsset,
  getVannaKnowledgeBase,
  listVannaSqlAssets,
  listVannaSqlAssetVersions,
  publishVannaSqlAsset,
  updateVannaSqlAsset,
} from "../shared/vanna-api"
import type {
  VannaKnowledgeBaseRecord,
  VannaSqlAssetRecord,
  VannaSqlAssetVersionRecord,
} from "../shared/vanna-types"

interface AssetEditFormState {
  asset_code: string
  name: string
  description: string
  intent_summary: string
  match_keywords: string
  match_examples: string
  template_sql: string
  version_label: string
}

function getStatusTone(status: string) {
  if (status === "published") {
    return "bg-emerald-500/10 text-emerald-600 border-emerald-200"
  }
  if (status === "draft") {
    return "bg-amber-500/10 text-amber-600 border-amber-200"
  }
  if (status === "archived") {
    return "bg-zinc-500/10 text-zinc-600 border-zinc-200"
  }
  return "bg-zinc-500/10 text-zinc-600 border-zinc-200"
}

function sourceLabel(asset: VannaSqlAssetRecord) {
  if (asset.origin_training_entry_id) {
    return `问答对 #${asset.origin_training_entry_id}`
  }
  if (asset.origin_ask_run_id) {
    return `Ask #${asset.origin_ask_run_id}`
  }
  return "手工资产"
}

function compactSql(sql?: string | null) {
  const normalized = (sql || "").replace(/\s+/g, " ").trim()
  if (!normalized) {
    return "暂无 SQL"
  }
  return normalized.length > 88 ? `${normalized.slice(0, 88)}...` : normalized
}

function splitCommaValues(input: string) {
  return input
    .split(",")
    .map(value => value.trim())
    .filter(Boolean)
}

export function KnowledgeBaseAssetsView() {
  const params = useParams()
  const kbId = Number(params.id)

  const [loading, setLoading] = useState(true)
  const [kb, setKb] = useState<VannaKnowledgeBaseRecord | null>(null)
  const [assets, setAssets] = useState<VannaSqlAssetRecord[]>([])
  const [searchTerm, setSearchTerm] = useState("")
  const [versionsByAssetId, setVersionsByAssetId] = useState<
    Record<number, VannaSqlAssetVersionRecord[]>
  >({})
  const [loadingVersionAssetId, setLoadingVersionAssetId] = useState<number | null>(null)
  const [detailTarget, setDetailTarget] = useState<VannaSqlAssetRecord | null>(null)
  const [editTarget, setEditTarget] = useState<VannaSqlAssetRecord | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<VannaSqlAssetRecord | null>(null)
  const [savingEdit, setSavingEdit] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [publishingAssetId, setPublishingAssetId] = useState<number | null>(null)
  const [editForm, setEditForm] = useState<AssetEditFormState>({
    asset_code: "",
    name: "",
    description: "",
    intent_summary: "",
    match_keywords: "",
    match_examples: "",
    template_sql: "",
    version_label: "",
  })

  async function loadData(showLoading = true) {
    if (!Number.isFinite(kbId)) {
      return []
    }

    if (showLoading) {
      setLoading(true)
    }

    try {
      const kbRow = await getVannaKnowledgeBase(kbId)
      const assetRows = await listVannaSqlAssets({
        system_short: kbRow.system_short,
        database_name: kbRow.database_name ?? undefined,
      })
      setKb(kbRow)
      setAssets(assetRows)
      return assetRows
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "加载 SQL 资产失败")
      return []
    } finally {
      if (showLoading) {
        setLoading(false)
      }
    }
  }

  useEffect(() => {
    void loadData()
  }, [kbId])

  const filteredAssets = useMemo(() => {
    const keyword = searchTerm.trim().toLowerCase()
    return [...assets]
      .filter(asset => {
        if (!keyword) {
          return true
        }
        const haystack = [
          asset.asset_code,
          asset.name,
          asset.description,
          asset.intent_summary,
          asset.database_name,
          asset.env,
          ...asset.match_keywords,
          ...asset.match_examples,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
        return haystack.includes(keyword)
      })
      .sort(
        (left, right) =>
          new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime()
      )
  }, [assets, searchTerm])

  const envCount = useMemo(() => {
    return Array.from(new Set(assets.map(asset => asset.env))).length
  }, [assets])

  function getCurrentVersion(asset: VannaSqlAssetRecord) {
    const versions = versionsByAssetId[asset.id] || []
    if (asset.current_version_id) {
      const matched = versions.find(version => version.id === asset.current_version_id)
      if (matched) {
        return matched
      }
    }
    return versions[0] || null
  }

  async function ensureVersions(asset: VannaSqlAssetRecord) {
    if (versionsByAssetId[asset.id]) {
      return versionsByAssetId[asset.id]
    }
    try {
      setLoadingVersionAssetId(asset.id)
      const rows = await listVannaSqlAssetVersions(asset.id)
      setVersionsByAssetId(current => ({
        ...current,
        [asset.id]: rows,
      }))
      return rows
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "加载资产版本失败")
      return []
    } finally {
      setLoadingVersionAssetId(current => (current === asset.id ? null : current))
    }
  }

  async function handleOpenDetail(asset: VannaSqlAssetRecord) {
    setEditTarget(null)
    setDetailTarget(asset)
    await ensureVersions(asset)
  }

  async function handleOpenEdit(asset: VannaSqlAssetRecord) {
    setDetailTarget(null)
    const versions = await ensureVersions(asset)
    const currentVersion =
      (asset.current_version_id
        ? versions.find(version => version.id === asset.current_version_id)
        : null) || versions[0] || null

    setEditForm({
      asset_code: asset.asset_code,
      name: asset.name,
      description: asset.description || "",
      intent_summary: asset.intent_summary || "",
      match_keywords: asset.match_keywords.join(", "),
      match_examples: asset.match_examples.join(", "),
      template_sql: currentVersion?.template_sql || "",
      version_label: "",
    })
    setEditTarget(asset)
  }

  async function handleSaveEdit() {
    if (!editTarget) {
      return
    }
    if (!editForm.asset_code.trim() || !editForm.name.trim() || !editForm.template_sql.trim()) {
      toast.error("资产编码、名称和 SQL 模板不能为空")
      return
    }

    try {
      setSavingEdit(true)
      await updateVannaSqlAsset(editTarget.id, {
        asset_code: editForm.asset_code.trim(),
        name: editForm.name.trim(),
        description: editForm.description.trim() || undefined,
        intent_summary: editForm.intent_summary.trim() || undefined,
        asset_kind: editTarget.asset_kind,
        match_keywords: splitCommaValues(editForm.match_keywords),
        match_examples: splitCommaValues(editForm.match_examples),
        template_sql: editForm.template_sql.trim(),
        version_label: editForm.version_label.trim() || undefined,
      })
      toast.success("SQL 资产已更新")
      setEditTarget(null)
      await loadData(false)
      setVersionsByAssetId(current => {
        const next = { ...current }
        delete next[editTarget.id]
        return next
      })
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "更新 SQL 资产失败")
    } finally {
      setSavingEdit(false)
    }
  }

  async function handleDeleteConfirm() {
    if (!deleteTarget) {
      return
    }
    try {
      setDeleting(true)
      await archiveVannaSqlAsset(deleteTarget.id)
      toast.success("SQL 资产已归档")
      setDeleteTarget(null)
      if (detailTarget?.id === deleteTarget.id) {
        setDetailTarget(null)
      }
      if (editTarget?.id === deleteTarget.id) {
        setEditTarget(null)
      }
      await loadData(false)
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "删除 SQL 资产失败")
    } finally {
      setDeleting(false)
    }
  }

  async function handlePublishAsset(asset: VannaSqlAssetRecord) {
    try {
      setPublishingAssetId(asset.id)
      const versions = await ensureVersions(asset)
      const targetVersion =
        (asset.current_version_id
          ? versions.find(version => version.id === asset.current_version_id)
          : null) || versions[0] || null

      if (!targetVersion) {
        toast.error("当前资产没有可发布的版本")
        return
      }

      await publishVannaSqlAsset(asset.id, {
        version_id: targetVersion.id,
      })

      const [assetRows, refreshedVersions] = await Promise.all([
        loadData(false),
        listVannaSqlAssetVersions(asset.id),
      ])

      setVersionsByAssetId(current => ({
        ...current,
        [asset.id]: refreshedVersions,
      }))

      const refreshedAsset = assetRows.find(row => row.id === asset.id) || null
      if (detailTarget?.id === asset.id) {
        setDetailTarget(refreshedAsset)
      }
      if (editTarget?.id === asset.id) {
        setEditTarget(refreshedAsset)
      }

      toast.success("SQL 资产已发布")
    } catch (error) {
      console.error(error)
      toast.error(error instanceof Error ? error.message : "发布 SQL 资产失败")
    } finally {
      setPublishingAssetId(current => (current === asset.id ? null : current))
    }
  }

  const detailVersion = detailTarget ? getCurrentVersion(detailTarget) : null

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-112px)] w-full items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100vh-112px)] w-full flex-col overflow-hidden bg-[linear-gradient(180deg,#fff_0%,#f8fafc_100%)]">
      <div className="z-10 flex shrink-0 items-center justify-between border-b bg-white/90 px-8 py-5 backdrop-blur">
        <div className="flex items-center gap-4">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10">
            <Sparkles className="h-4 w-4 text-primary" />
          </div>
          <div>
            <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.28em] text-muted-foreground">
              SQL Assets
            </div>
            <div className="mt-1 text-base font-black tracking-tight">
              {kb?.system_short || "-"} SQL 资产列表
            </div>
            <div className="text-xs text-muted-foreground">
              当前数据库 {kb?.database_name || "-"} 下共 {assets.length} 条资产，覆盖 {envCount} 个环境
            </div>
          </div>
        </div>
        <Badge variant="outline" className="rounded-full px-4 py-1.5 text-xs font-bold">
          {kb?.database_name || "-"} / {kb?.env || "-"}
        </Badge>
      </div>

      <div className="flex shrink-0 items-center justify-between gap-4 border-b bg-white/70 px-8 py-4">
        <div className="relative w-full max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchTerm}
            onChange={event => setSearchTerm(event.target.value)}
            placeholder="搜索资产编码、名称、描述、关键词..."
            className="h-10 rounded-2xl border-none bg-zinc-100/90 pl-9 text-sm shadow-inner"
          />
        </div>
        <Badge variant="outline" className="rounded-full px-3 py-1 text-[11px] font-bold">
          共 {filteredAssets.length} 条
        </Badge>
      </div>

      <div className="flex-1 overflow-auto px-8 py-6">
        <div className="overflow-hidden rounded-[1.75rem] border bg-white shadow-[0_20px_60px_rgba(15,23,42,0.06)]">
          <Table>
            <TableHeader className="bg-zinc-50/80">
              <TableRow className="hover:bg-zinc-50/80">
                <TableHead className="w-[14%]">资产编码</TableHead>
                <TableHead className="w-[18%]">资产名称</TableHead>
                <TableHead className="w-[20%]">SQL 摘要</TableHead>
                <TableHead className="w-[12%]">来源</TableHead>
                <TableHead className="w-[10%]">状态</TableHead>
                <TableHead className="w-[8%]">环境</TableHead>
                <TableHead className="w-[10%]">更新时间</TableHead>
                <TableHead className="w-[18%] text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredAssets.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="py-12 text-center text-sm text-muted-foreground">
                    当前系统下还没有 SQL 资产。
                  </TableCell>
                </TableRow>
              ) : (
                filteredAssets.map(asset => {
                  const currentVersion = getCurrentVersion(asset)
                  return (
                    <TableRow key={asset.id}>
                      <TableCell className="align-top">
                        <div className="font-mono text-xs font-bold text-primary/80">
                          {asset.asset_code}
                        </div>
                      </TableCell>
                      <TableCell className="align-top">
                        <div className="space-y-1">
                          <div className="text-sm font-black">{asset.name}</div>
                          <div className="line-clamp-2 text-xs text-muted-foreground">
                            {asset.intent_summary || asset.description || "暂无描述"}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="align-top">
                        <div className="font-mono text-xs leading-5 text-zinc-700">
                          {currentVersion
                            ? compactSql(currentVersion.template_sql)
                            : loadingVersionAssetId === asset.id
                              ? "正在加载版本..."
                              : "点击查看详情加载 SQL"}
                        </div>
                      </TableCell>
                      <TableCell className="align-top text-sm text-muted-foreground">
                        {sourceLabel(asset)}
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge
                          variant="outline"
                          className={cn("rounded-full", getStatusTone(asset.status))}
                        >
                          {asset.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="align-top text-sm">{asset.env}</TableCell>
                      <TableCell className="align-top text-sm text-muted-foreground">
                        {formatDate(asset.updated_at)}
                      </TableCell>
                      <TableCell className="align-top">
                        <div className="flex justify-end gap-2">
                          {asset.status === "draft" ? (
                            <Button
                              size="sm"
                              className="rounded-full"
                              onClick={() => void handlePublishAsset(asset)}
                              disabled={publishingAssetId === asset.id}
                            >
                              {publishingAssetId === asset.id ? (
                                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                              ) : null}
                              发布
                            </Button>
                          ) : null}
                          <Button
                            variant="outline"
                            size="sm"
                            className="rounded-full"
                            onClick={() => void handleOpenDetail(asset)}
                          >
                            <Eye className="mr-1 h-3.5 w-3.5" />
                            查看详情
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="rounded-full"
                            onClick={() => void handleOpenEdit(asset)}
                          >
                            <Edit2 className="mr-1 h-3.5 w-3.5" />
                            修改
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="rounded-full text-red-600 hover:text-red-600"
                            onClick={() => setDeleteTarget(asset)}
                          >
                            <Trash2 className="mr-1 h-3.5 w-3.5" />
                            删除
                          </Button>
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

      <Dialog open={Boolean(detailTarget)} onOpenChange={open => !open && setDetailTarget(null)}>
        <DialogContent className="max-h-[85vh] max-w-5xl overflow-hidden">
          {detailTarget ? (
            <>
              <DialogHeader>
                <DialogTitle>SQL 资产详情</DialogTitle>
                <DialogDescription>
                  查看资产元信息、来源和当前版本 SQL 模板。
                </DialogDescription>
              </DialogHeader>

              <div className="min-h-0 space-y-6 overflow-y-auto pr-2">
                <div className="flex justify-end">
                  {detailTarget.status === "draft" ? (
                    <Button
                      className="rounded-full"
                      onClick={() => void handlePublishAsset(detailTarget)}
                      disabled={publishingAssetId === detailTarget.id}
                    >
                      {publishingAssetId === detailTarget.id ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : null}
                      发布当前资产
                    </Button>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className={getStatusTone(detailTarget.status)}>
                    {detailTarget.status}
                  </Badge>
                  <Badge variant="outline">{detailTarget.asset_code}</Badge>
                  <Badge variant="outline">{detailTarget.database_name || "-"}</Badge>
                  <Badge variant="outline">{detailTarget.env}</Badge>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-3xl border bg-zinc-50 p-5">
                    <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                      资产名称
                    </div>
                    <div className="mt-3 text-base font-black">{detailTarget.name}</div>
                  </div>
                  <div className="rounded-3xl border bg-zinc-50 p-5">
                    <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                      来源
                    </div>
                    <div className="mt-3 text-sm">{sourceLabel(detailTarget)}</div>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-3xl border bg-white p-5">
                    <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                      描述
                    </div>
                    <div className="mt-3 text-sm leading-7">
                      {detailTarget.description || "暂无描述"}
                    </div>
                  </div>
                  <div className="rounded-3xl border bg-white p-5">
                    <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                      用途摘要
                    </div>
                    <div className="mt-3 text-sm leading-7">
                      {detailTarget.intent_summary || "暂无用途摘要"}
                    </div>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-3xl border bg-white p-5">
                    <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                      匹配关键词
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {detailTarget.match_keywords.length > 0 ? (
                        detailTarget.match_keywords.map((keyword, index) => (
                          <Badge key={`${keyword}-${index}`} variant="outline">
                            {keyword}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-sm text-muted-foreground">暂无关键词</span>
                      )}
                    </div>
                  </div>
                  <div className="rounded-3xl border bg-white p-5">
                    <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                      匹配示例
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {detailTarget.match_examples.length > 0 ? (
                        detailTarget.match_examples.map((example, index) => (
                          <Badge key={`${example}-${index}`} variant="outline">
                            {example}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-sm text-muted-foreground">暂无示例</span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                    当前 SQL 模板
                  </div>
                  <div className="rounded-3xl bg-zinc-950 p-6 text-zinc-100">
                    {loadingVersionAssetId === detailTarget.id && !detailVersion ? (
                      <div className="flex items-center gap-2 text-sm text-zinc-400">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        正在加载版本信息...
                      </div>
                    ) : (
                      <pre className="overflow-auto whitespace-pre-wrap break-all font-mono text-xs leading-6">
                        {detailVersion?.template_sql || "暂无 SQL 模板"}
                      </pre>
                    )}
                  </div>
                </div>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(editTarget)} onOpenChange={open => !open && setEditTarget(null)}>
        <DialogContent className="max-h-[85vh] max-w-5xl overflow-hidden">
          {editTarget ? (
            <>
              <DialogHeader>
                <DialogTitle>修改 SQL 资产</DialogTitle>
                <DialogDescription>
                  保存后会更新资产元信息，并基于当前版本 SQL 生成一个新版本。
                </DialogDescription>
              </DialogHeader>

              <div className="min-h-0 space-y-6 overflow-y-auto pr-2">
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label>资产编码</Label>
                    <Input
                      value={editForm.asset_code}
                      onChange={event =>
                        setEditForm(current => ({
                          ...current,
                          asset_code: event.target.value,
                        }))
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>资产名称</Label>
                    <Input
                      value={editForm.name}
                      onChange={event =>
                        setEditForm(current => ({
                          ...current,
                          name: event.target.value,
                        }))
                      }
                    />
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label>描述</Label>
                    <Textarea
                      value={editForm.description}
                      onChange={event =>
                        setEditForm(current => ({
                          ...current,
                          description: event.target.value,
                        }))
                      }
                      className="min-h-28"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>用途摘要</Label>
                    <Textarea
                      value={editForm.intent_summary}
                      onChange={event =>
                        setEditForm(current => ({
                          ...current,
                          intent_summary: event.target.value,
                        }))
                      }
                      className="min-h-28"
                    />
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label>匹配关键词</Label>
                    <Input
                      value={editForm.match_keywords}
                      onChange={event =>
                        setEditForm(current => ({
                          ...current,
                          match_keywords: event.target.value,
                        }))
                      }
                      placeholder="用英文逗号分隔"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>匹配示例</Label>
                    <Input
                      value={editForm.match_examples}
                      onChange={event =>
                        setEditForm(current => ({
                          ...current,
                          match_examples: event.target.value,
                        }))
                      }
                      placeholder="用英文逗号分隔"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>新版本标签</Label>
                  <Input
                    value={editForm.version_label}
                    onChange={event =>
                      setEditForm(current => ({
                        ...current,
                        version_label: event.target.value,
                      }))
                    }
                    placeholder="例如 v2 或 2026-04-06"
                  />
                </div>

                <div className="space-y-2">
                  <Label>当前版本 SQL 模板</Label>
                  <Textarea
                    value={editForm.template_sql}
                    onChange={event =>
                      setEditForm(current => ({
                        ...current,
                        template_sql: event.target.value,
                      }))
                    }
                    className="min-h-[260px] rounded-3xl border-none bg-zinc-950 p-6 font-mono text-sm leading-6 text-zinc-100 shadow-2xl"
                  />
                </div>

                <div className="flex justify-end gap-3">
                  <Button
                    variant="outline"
                    className="rounded-full"
                    onClick={() => setEditTarget(null)}
                    disabled={savingEdit}
                  >
                    取消
                  </Button>
                  <Button
                    className="rounded-full"
                    onClick={() => void handleSaveEdit()}
                    disabled={savingEdit}
                  >
                    {savingEdit ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    保存修改
                  </Button>
                </div>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        isOpen={Boolean(deleteTarget)}
        onOpenChange={open => !open && setDeleteTarget(null)}
        onConfirm={() => void handleDeleteConfirm()}
        isLoading={deleting}
        title="删除 SQL 资产"
        description={
          deleteTarget
            ? `确认删除“${deleteTarget.name}”吗？删除会把该资产归档，并从当前列表中隐藏。`
            : ""
        }
        confirmText="确认删除"
      />
    </div>
  )
}
