"use client"

import React, { useEffect, useState } from "react"
import { useParams, usePathname, useRouter } from "next/navigation"
import { Database, Activity, BookOpen, CheckSquare, History, Play, ChevronLeft, MoreVertical, Settings2, ShieldCheck, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { getVannaKnowledgeBase } from "./vanna-api"
import type { VannaKnowledgeBaseRecord } from "./vanna-types"

interface NavItem {
  id: string
  label: string
  icon: React.ElementType
  href: string
}

export function KnowledgeBaseLayout({ children }: { children: React.ReactNode }) {
  const params = useParams()
  const pathname = usePathname()
  const router = useRouter()
  const id = params.id as string

  const [kb, setKb] = useState<VannaKnowledgeBaseRecord | null>(null)

  useEffect(() => {
    if (!id) return
    getVannaKnowledgeBase(Number(id))
      .then(setKb)
      .catch(() => {/* 加载失败时 header 保持空白，不影响子页面 */})
  }, [id])

  const navItems: NavItem[] = [
    { id: "overview", label: "工作台总览", icon: Activity, href: `/knowledge-bases/${id}` },
    { id: "facts", label: "结构事实", icon: Database, href: `/knowledge-bases/${id}/facts` },
    { id: "training", label: "训练知识", icon: BookOpen, href: `/knowledge-bases/${id}/training` },
    { id: "review", label: "候评审核", icon: CheckSquare, href: `/knowledge-bases/${id}/review` },
    { id: "runs", label: "运行记录", icon: History, href: `/knowledge-bases/${id}/runs` },
  ]

  const activeItem = navItems.find(item => pathname === item.href) || navItems[0]

  return (
    <div className="flex flex-col h-screen w-full bg-zinc-50/50 dark:bg-zinc-950/50 overflow-hidden text-foreground font-sans">
      
      {/* 1. 固定页眉：知识库身份与基础信息 */}
      <header className="shrink-0 bg-background border-b z-30 shadow-sm">
        <div className="h-16 px-8 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button 
              variant="ghost" 
              size="icon" 
              className="rounded-full h-9 w-9 -ml-2" 
              onClick={() => router.push("/knowledge-bases")}
            >
              <ChevronLeft className="w-5 h-5" />
            </Button>
            <div className="flex items-center gap-3">
              <div className="p-2 bg-primary/10 rounded-xl">
                <Database className="w-5 h-5 text-primary" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  {kb ? (
                    <>
                      <h1 className="text-lg font-black tracking-tight">{kb.name}</h1>
                      <Badge variant="outline" className={cn(
                        "px-2 py-0 text-[10px] uppercase font-bold",
                        kb.status === "active"
                          ? "bg-emerald-500/10 text-emerald-600 border-emerald-200/50"
                          : "bg-zinc-500/10 text-zinc-500 border-zinc-200/50"
                      )}>{kb.status}</Badge>
                    </>
                  ) : (
                    <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                  )}
                </div>
                <div className="flex items-center gap-2 text-[10px] font-mono text-muted-foreground uppercase tracking-wider">
                  <span>ID: {id}</span>
                  {kb && (
                    <>
                      <span className="w-1 h-1 rounded-full bg-border" />
                      <span>{kb.kb_code}</span>
                      <span className="w-1 h-1 rounded-full bg-border" />
                      <span className="flex items-center gap-1"><ShieldCheck className="w-2.5 h-2.5" /> {kb.env}</span>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="rounded-full h-9 px-4 text-xs font-bold gap-2 bg-background border-dashed">
              <Settings2 className="w-3.5 h-3.5" /> 知识库设置
            </Button>
            <Button size="sm" className="rounded-full h-9 px-6 text-xs font-bold gap-2 shadow-lg shadow-primary/20" onClick={() => router.push(`/knowledge-bases/${id}/harvest`)}>
              <Play className="w-3.5 h-3.5" /> 重新采集元数据
            </Button>
            <div className="w-px h-4 bg-border mx-2" />
            <Button variant="ghost" size="icon" className="rounded-full h-9 w-9 text-muted-foreground">
              <MoreVertical className="w-4 h-4" />
            </Button>
          </div>
        </div>

        {/* 2. 固定标签页：类似快捷操作的 Tab */}
        <nav className="h-12 px-8 flex items-center gap-1 bg-zinc-50/50 dark:bg-zinc-900/20">
          {navItems.map((item) => {
            const isActive = pathname === item.href
            return (
              <button
                key={item.id}
                onClick={() => router.push(item.href)}
                className={cn(
                  "h-full px-5 flex items-center gap-2 text-xs font-bold transition-all relative group",
                  isActive 
                    ? "text-primary bg-background border-x border-t border-border shadow-[0_-2px_10px_rgba(0,0,0,0.02)] rounded-t-xl" 
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <item.icon className={cn("w-3.5 h-3.5", isActive ? "text-primary" : "opacity-50 group-hover:opacity-100")} />
                {item.label}
                {isActive && (
                  <div className="absolute -bottom-px left-0 right-0 h-px bg-background z-10" />
                )}
              </button>
            )
          })}
        </nav>
      </header>

      {/* 3. 动态内容区域：可独立滚动 */}
      <main className="flex-1 overflow-y-auto relative bg-white dark:bg-zinc-950">
        <div className="min-h-full">
          {children}
        </div>
      </main>
    </div>
  )
}
