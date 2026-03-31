"use client"

import React, { useEffect, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { Database, Plus, Search, Clock, ChevronRight, Loader2 } from "lucide-react"
import { getApiUrl } from "@/lib/utils"
import { apiRequest } from "@/lib/api-wrapper"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "sonner"

export default function DataMakeListPage() {
  const [tasks, setTasks] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false)
  const [newPrompt, setNewPrompt] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const router = useRouter()

  const fetchTasks = async () => {
    try {
      const res = await apiRequest(`${getApiUrl()}/api/chat/tasks?agent_type=datamake&per_page=50`)
      if (res.ok) {
        const data = await res.json()
        setTasks(data.tasks || [])
      }
    } catch (err) {
      console.error("Failed to fetch datamake tasks", err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTasks()
  }, [])

  const handleCreateNew = async () => {
    if (!newPrompt.trim()) return
    
    setIsSubmitting(true)
    try {
      const res = await apiRequest(`${getApiUrl()}/api/v1/datamake/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input: newPrompt })
      })
      
      if (!res.ok) throw new Error("Failed to create task")
      
      const data = await res.json()
      toast.success("造数任务已启动")
      router.push(`/datamake/${data.task_id}`)
    } catch (err) {
      console.error(err)
      toast.error("启动失败，请检查后端连接")
    } finally {
      setIsSubmitting(false)
      setIsCreateDialogOpen(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-slate-50">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-screen w-full bg-slate-50 overflow-hidden text-slate-800">
      <header className="h-16 bg-white border-b flex items-center justify-between px-8 shrink-0">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-blue-600 rounded-lg">
            <Database className="w-5 h-5 text-white" />
          </div>
          <h1 className="text-xl font-bold text-slate-800">智能造数工作台</h1>
        </div>
        <Button 
          onClick={() => setIsCreateDialogOpen(true)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white"
        >
          <Plus className="w-4 h-4" />
          发起新造数任务
        </Button>
      </header>

      <main className="flex-1 overflow-y-auto p-8">
        <div className="max-w-5xl mx-auto">
          <div className="mb-8">
            <h2 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-2">活跃中的造数工程</h2>
            <p className="text-slate-500 text-sm">管理您的自动化数据生成、表结构探测与 SQL 推演任务。</p>
          </div>

          {tasks.length === 0 ? (
            <div className="bg-white border rounded-xl p-16 flex flex-col items-center justify-center text-center shadow-sm">
              <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mb-4">
                <Database className="w-8 h-8 text-slate-400" />
              </div>
              <h3 className="text-lg font-bold">暂无造数任务</h3>
              <p className="text-slate-500 mt-2 max-w-xs">
                您还没有发起过专门的造数任务。点击右上角按钮开始您的第一个数据生成实验。
              </p>
            </div>
          ) : (
            <div className="grid gap-4">
              {tasks.map(task => (
                <Link 
                  key={task.task_id} 
                  href={`/datamake/${task.task_id}`}
                  className="group bg-white border rounded-xl p-5 hover:border-blue-400 hover:shadow-md transition-all flex items-center justify-between"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center group-hover:bg-blue-600 group-hover:text-white transition-colors">
                      <Database className="w-5 h-5" />
                    </div>
                    <div>
                      <h4 className="font-bold group-hover:text-blue-600 transition-colors">
                        {task.title || "未命名造数任务"}
                      </h4>
                      <div className="flex items-center gap-3 mt-1">
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase ${
                          task.status === 'completed' ? 'bg-green-100 text-green-700' :
                          task.status === 'running' ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-600'
                        }`}>
                          {task.status}
                        </span>
                        <div className="flex items-center gap-1 text-slate-400 text-xs">
                          <Clock className="w-3 h-3" />
                          {task.created_at}
                        </div>
                      </div>
                    </div>
                  </div>
                  <ChevronRight className="w-5 h-5 text-slate-300 group-hover:text-blue-500 transform group-hover:translate-x-1 transition-all" />
                </Link>
              ))}
            </div>
          )}
        </div>
      </main>

      {/* 创建任务对话框 */}
      <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>发起造数任务</DialogTitle>
            <DialogDescription>
              请描述您想要生成的业务数据场景（例如：为订单表生成100条符合本月趋势的测试数据）。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <Textarea
              placeholder="请输入您的造数需求..."
              className="min-h-[120px]"
              value={newPrompt}
              onChange={(e) => setNewPrompt(e.target.value)}
              disabled={isSubmitting}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setIsCreateDialogOpen(false)}
              disabled={isSubmitting}
            >
              取消
            </Button>
            <Button 
              type="button" 
              onClick={handleCreateNew}
              disabled={!newPrompt.trim() || isSubmitting}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  正在启动...
                </>
              ) : (
                "立即启动"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
