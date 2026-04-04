"use client"

import React, { useCallback, useEffect, useMemo, useState } from "react"
import {
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Shield,
  ShieldCheck,
  Users,
} from "lucide-react"

import { useAuth } from "@/contexts/auth-context"
import { apiRequest } from "@/lib/api-wrapper"
import { getApiErrorMessage } from "@/lib/api-errors"
import { getApiUrl } from "@/lib/utils"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select as SelectRadix,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select-radix"

type SystemRegistryItem = {
  system_short: string
  display_name: string
  description?: string | null
  status: "active" | "disabled"
  member_count: number
  system_admin_count: number
  created_at?: string | null
  updated_at?: string | null
}

type UserOption = {
  id: number
  username: string
  is_admin?: boolean
}

type SystemMemberItem = {
  id: number
  user_id: number
  username?: string
  system_short: string
  role: "member" | "system_admin"
  granted_by: number
  created_at?: string | null
}

type SystemFormState = {
  system_short: string
  display_name: string
  description: string
  status: "active" | "disabled"
}

const EMPTY_SYSTEM_FORM: SystemFormState = {
  system_short: "",
  display_name: "",
  description: "",
  status: "active",
}

export default function SystemRegistryPage() {
  const { user } = useAuth()
  const [systems, setSystems] = useState<SystemRegistryItem[]>([])
  const [users, setUsers] = useState<UserOption[]>([])
  const [members, setMembers] = useState<SystemMemberItem[]>([])
  const [loading, setLoading] = useState(true)
  const [systemDialogOpen, setSystemDialogOpen] = useState(false)
  const [memberDialogOpen, setMemberDialogOpen] = useState(false)
  const [editingSystemShort, setEditingSystemShort] = useState<string | null>(null)
  const [selectedSystem, setSelectedSystem] = useState<SystemRegistryItem | null>(null)
  const [keyword, setKeyword] = useState("")
  const [systemForm, setSystemForm] = useState<SystemFormState>(EMPTY_SYSTEM_FORM)
  const [submittingSystem, setSubmittingSystem] = useState(false)
  const [submittingMember, setSubmittingMember] = useState(false)
  const [memberUserId, setMemberUserId] = useState("")
  const [memberRole, setMemberRole] = useState<"member" | "system_admin">("member")

  const loadSystems = useCallback(async () => {
    setLoading(true)
    try {
      const response = await apiRequest(`${getApiUrl()}/api/system-registry`)
      if (!response.ok) {
        const error = await response.json().catch(() => null)
        toast.error(getApiErrorMessage(error, "加载系统列表失败"))
        return
      }
      const payload = await response.json()
      setSystems(payload.data || [])
    } catch (error) {
      console.error(error)
      toast.error("加载系统列表失败")
    } finally {
      setLoading(false)
    }
  }, [])

  const loadUsers = useCallback(async () => {
    try {
      const response = await apiRequest(`${getApiUrl()}/api/admin/users?page=1&size=100`)
      if (!response.ok) {
        return
      }
      const payload = await response.json()
      setUsers(payload.users || [])
    } catch (error) {
      console.error(error)
    }
  }, [])

  const loadMembers = useCallback(async (systemShort: string) => {
    try {
      const response = await apiRequest(
        `${getApiUrl()}/api/system-registry/${systemShort}/members`
      )
      if (!response.ok) {
        const error = await response.json().catch(() => null)
        toast.error(getApiErrorMessage(error, "加载系统成员失败"))
        return
      }
      const payload = await response.json()
      setMembers(payload.data || [])
    } catch (error) {
      console.error(error)
      toast.error("加载系统成员失败")
    }
  }, [])

  useEffect(() => {
    if (user?.is_admin) {
      void loadSystems()
      void loadUsers()
    }
  }, [loadSystems, loadUsers, user])

  const filteredSystems = useMemo(() => {
    const search = keyword.trim().toLowerCase()
    if (!search) return systems
    return systems.filter(item =>
      [item.system_short, item.display_name, item.description]
        .filter(Boolean)
        .some(value => String(value).toLowerCase().includes(search))
    )
  }, [keyword, systems])

  const openCreateSystemDialog = () => {
    setEditingSystemShort(null)
    setSystemForm(EMPTY_SYSTEM_FORM)
    setSystemDialogOpen(true)
  }

  const openEditSystemDialog = (system: SystemRegistryItem) => {
    setEditingSystemShort(system.system_short)
    setSystemForm({
      system_short: system.system_short,
      display_name: system.display_name,
      description: system.description || "",
      status: system.status,
    })
    setSystemDialogOpen(true)
  }

  const openMembersDialog = async (system: SystemRegistryItem) => {
    setSelectedSystem(system)
    setMemberUserId("")
    setMemberRole("member")
    setMemberDialogOpen(true)
    await loadMembers(system.system_short)
  }

  const submitSystem = async () => {
    if (!systemForm.system_short.trim()) {
      toast.error("请填写 system_short")
      return
    }
    if (!systemForm.display_name.trim()) {
      toast.error("请填写系统名称")
      return
    }

    setSubmittingSystem(true)
    try {
      const response = await apiRequest(
        editingSystemShort
          ? `${getApiUrl()}/api/system-registry/${editingSystemShort}`
          : `${getApiUrl()}/api/system-registry`,
        {
          method: editingSystemShort ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...(editingSystemShort ? {} : { system_short: systemForm.system_short.trim() }),
            display_name: systemForm.display_name.trim(),
            description: systemForm.description.trim() || null,
            status: systemForm.status,
          }),
        }
      )

      if (!response.ok) {
        const error = await response.json().catch(() => null)
        toast.error(getApiErrorMessage(error, "保存系统失败"))
        return
      }

      toast.success(editingSystemShort ? "系统信息已更新" : "系统已创建")
      setSystemDialogOpen(false)
      await loadSystems()
    } catch (error) {
      console.error(error)
      toast.error("保存系统失败")
    } finally {
      setSubmittingSystem(false)
    }
  }

  const submitMember = async () => {
    if (!selectedSystem) return
    if (!memberUserId) {
      toast.error("请选择用户")
      return
    }

    setSubmittingMember(true)
    try {
      const response = await apiRequest(
        `${getApiUrl()}/api/system-registry/${selectedSystem.system_short}/members`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: Number(memberUserId),
            role: memberRole,
          }),
        }
      )

      if (!response.ok) {
        const error = await response.json().catch(() => null)
        toast.error(getApiErrorMessage(error, "分配系统角色失败"))
        return
      }

      toast.success("系统角色已分配")
      setMemberUserId("")
      setMemberRole("member")
      await loadMembers(selectedSystem.system_short)
      await loadSystems()
    } catch (error) {
      console.error(error)
      toast.error("分配系统角色失败")
    } finally {
      setSubmittingMember(false)
    }
  }

  const removeMember = async (member: SystemMemberItem) => {
    if (!selectedSystem) return
    if (!window.confirm(`确认移除用户 ${member.username || member.user_id} 的系统角色吗？`)) {
      return
    }

    try {
      const response = await apiRequest(
        `${getApiUrl()}/api/system-registry/${selectedSystem.system_short}/members/${member.user_id}`,
        { method: "DELETE" }
      )
      if (!response.ok) {
        const error = await response.json().catch(() => null)
        toast.error(getApiErrorMessage(error, "移除系统角色失败"))
        return
      }

      toast.success("系统角色已移除")
      await loadMembers(selectedSystem.system_short)
      await loadSystems()
    } catch (error) {
      console.error(error)
      toast.error("移除系统角色失败")
    }
  }

  const updateMemberRole = async (
    member: SystemMemberItem,
    nextRole: "member" | "system_admin"
  ) => {
    if (!selectedSystem || member.role === nextRole) return

    try {
      const response = await apiRequest(
        `${getApiUrl()}/api/system-registry/${selectedSystem.system_short}/members/${member.user_id}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role: nextRole }),
        }
      )
      if (!response.ok) {
        const error = await response.json().catch(() => null)
        toast.error(getApiErrorMessage(error, "更新系统角色失败"))
        return
      }

      toast.success("系统角色已更新")
      await loadMembers(selectedSystem.system_short)
      await loadSystems()
    } catch (error) {
      console.error(error)
      toast.error("更新系统角色失败")
    }
  }

  if (user && !user.is_admin) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <h2 className="text-2xl font-semibold mb-2">无权限访问</h2>
          <p className="text-muted-foreground">只有全局管理员可以维护 system_short 与系统角色。</p>
        </div>
      </div>
    )
  }

  if (!user) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <h2 className="text-2xl font-semibold mb-2">加载中</h2>
          <p className="text-muted-foreground">正在读取当前用户信息。</p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto bg-[#0E1117]">
      <div className="p-8 space-y-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-1">系统管理</h1>
            <p className="text-muted-foreground">
              维护 `system_short` 主数据，并为用户分配 `member / system_admin`。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => void loadSystems()} disabled={loading}>
              <RefreshCw className="w-4 h-4 mr-2" />
              刷新
            </Button>
            <Button onClick={openCreateSystemDialog}>
              <Plus className="w-4 h-4 mr-2" />
              新建系统
            </Button>
          </div>
        </div>

        <Card className="bg-card/50 border-border">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5" />
              系统主数据
            </CardTitle>
            <CardDescription>审批边界、成员角色与资产归属均以 `system_short` 为准。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="relative max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-10"
                placeholder="搜索 system_short / display_name"
                value={keyword}
                onChange={event => setKeyword(event.target.value)}
              />
            </div>

            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>system_short</TableHead>
                    <TableHead>系统名称</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>成员数</TableHead>
                    <TableHead>系统管理员</TableHead>
                    <TableHead>更新时间</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {loading ? (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                        正在加载系统列表...
                      </TableCell>
                    </TableRow>
                  ) : filteredSystems.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                        暂无系统记录
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredSystems.map(system => (
                      <TableRow key={system.system_short}>
                        <TableCell className="font-mono font-medium">{system.system_short}</TableCell>
                        <TableCell>
                          <div className="font-medium">{system.display_name}</div>
                          {system.description ? (
                            <div className="text-xs text-muted-foreground mt-1">{system.description}</div>
                          ) : null}
                        </TableCell>
                        <TableCell>
                          <Badge variant={system.status === "active" ? "default" : "secondary"}>
                            {system.status}
                          </Badge>
                        </TableCell>
                        <TableCell>{system.member_count}</TableCell>
                        <TableCell>{system.system_admin_count}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {system.updated_at ? new Date(system.updated_at).toLocaleString() : "-"}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-2">
                            <Button variant="outline" size="sm" onClick={() => openMembersDialog(system)}>
                              <Users className="w-4 h-4 mr-1" />
                              成员
                            </Button>
                            <Button variant="outline" size="sm" onClick={() => openEditSystemDialog(system)}>
                              <Settings2 className="w-4 h-4 mr-1" />
                              编辑
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>

      <Dialog open={systemDialogOpen} onOpenChange={setSystemDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingSystemShort ? "编辑系统" : "新建系统"}</DialogTitle>
            <DialogDescription>创建后，审批与角色都会围绕这个 `system_short` 组织。</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label>system_short</Label>
              <Input
                value={systemForm.system_short}
                disabled={Boolean(editingSystemShort)}
                onChange={event =>
                  setSystemForm(current => ({
                    ...current,
                    system_short: event.target.value.toUpperCase(),
                  }))
                }
                placeholder="CRM"
              />
            </div>

            <div className="space-y-2">
              <Label>系统名称</Label>
              <Input
                value={systemForm.display_name}
                onChange={event =>
                  setSystemForm(current => ({ ...current, display_name: event.target.value }))
                }
                placeholder="客户关系管理系统"
              />
            </div>

            <div className="space-y-2">
              <Label>描述</Label>
              <Textarea
                value={systemForm.description}
                onChange={event =>
                  setSystemForm(current => ({ ...current, description: event.target.value }))
                }
                placeholder="该系统的业务范围、审批边界和资产说明"
              />
            </div>

            <div className="space-y-2">
              <Label>状态</Label>
              <SelectRadix
                value={systemForm.status}
                onValueChange={value =>
                  setSystemForm(current => ({
                    ...current,
                    status: value as "active" | "disabled",
                  }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">active</SelectItem>
                  <SelectItem value="disabled">disabled</SelectItem>
                </SelectContent>
              </SelectRadix>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setSystemDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void submitSystem()} disabled={submittingSystem}>
              {submittingSystem ? "保存中..." : editingSystemShort ? "更新" : "创建"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={memberDialogOpen} onOpenChange={setMemberDialogOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Shield className="h-5 w-5" />
              {selectedSystem?.system_short} 成员管理
            </DialogTitle>
            <DialogDescription>全局管理员在这里分配 `member / system_admin`。</DialogDescription>
          </DialogHeader>

          <div className="grid grid-cols-12 gap-3 items-end">
            <div className="col-span-6 space-y-2">
              <Label>用户</Label>
              <SelectRadix value={memberUserId} onValueChange={setMemberUserId}>
                <SelectTrigger>
                  <SelectValue placeholder="选择一个用户" />
                </SelectTrigger>
                <SelectContent>
                  {users.map(option => (
                    <SelectItem key={option.id} value={String(option.id)}>
                      {option.username} (#{option.id})
                    </SelectItem>
                  ))}
                </SelectContent>
              </SelectRadix>
            </div>

            <div className="col-span-4 space-y-2">
              <Label>角色</Label>
              <SelectRadix
                value={memberRole}
                onValueChange={value => setMemberRole(value as "member" | "system_admin")}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="member">member</SelectItem>
                  <SelectItem value="system_admin">system_admin</SelectItem>
                </SelectContent>
              </SelectRadix>
            </div>

            <div className="col-span-2">
              <Button className="w-full" onClick={() => void submitMember()} disabled={submittingMember}>
                添加
              </Button>
            </div>
          </div>

          <div className="rounded-md border max-h-[420px] overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>用户</TableHead>
                  <TableHead>角色</TableHead>
                  <TableHead>授予时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="py-10 text-center text-muted-foreground">
                      当前系统还没有成员
                    </TableCell>
                  </TableRow>
                ) : (
                  members.map(member => (
                    <TableRow key={member.id}>
                      <TableCell>
                        <div className="font-medium">{member.username || `#${member.user_id}`}</div>
                        <div className="text-xs text-muted-foreground">user_id: {member.user_id}</div>
                      </TableCell>
                      <TableCell>
                        <SelectRadix
                          value={member.role}
                          onValueChange={value =>
                            void updateMemberRole(
                              member,
                              value as "member" | "system_admin"
                            )
                          }
                        >
                          <SelectTrigger className="w-[170px]">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="member">member</SelectItem>
                            <SelectItem value="system_admin">system_admin</SelectItem>
                          </SelectContent>
                        </SelectRadix>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {member.created_at ? new Date(member.created_at).toLocaleString() : "-"}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="outline" size="sm" onClick={() => void removeMember(member)}>
                          移除
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
