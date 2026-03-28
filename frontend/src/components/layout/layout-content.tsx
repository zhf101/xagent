"use client"

import { usePathname } from "next/navigation"
import { Sidebar } from "@/components/layout/sidebar"
import { AppProvider } from "@/contexts/app-context-chat"
import { useAuth } from "@/contexts/auth-context"
import { isAuthPublicPath } from "@/lib/auth-pages"
import { cn } from "@/lib/utils"
import { useState, useEffect } from "react"
import { PanelLeftClose, PanelLeftOpen } from "lucide-react"

const SIDEBAR_VISIBLE_KEY = "xagent.sidebar.visible"

interface LayoutContentProps {
  children: React.ReactNode
}

export function LayoutContent({ children }: LayoutContentProps) {
  const pathname = usePathname()
  const { token } = useAuth()
  const isAuthPage = isAuthPublicPath(pathname)
  
  // 侧边栏显示状态 - 默认显示
  const [sidebarVisible, setSidebarVisible] = useState(true)

  // 从本地存储恢复状态
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(SIDEBAR_VISIBLE_KEY)
      if (saved !== null) {
        setSidebarVisible(saved === "1")
      }
    } catch {
      // ignore
    }
  }, [])

  // 保存状态到本地存储
  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_VISIBLE_KEY, sidebarVisible ? "1" : "0")
    } catch {
      // ignore
    }
  }, [sidebarVisible])

  if (isAuthPage) {
    // For auth pages, just render children without sidebar
    return <>{children}</>
  }

  // For other pages, show sidebar and main layout
  return (
    <AppProvider token={token || undefined}>
      <div className="flex h-screen bg-background relative">
        {/* 侧边栏 */}
        {sidebarVisible && <Sidebar />}
        
        {/* 主内容区域 */}
        <main className="flex-1 flex flex-col overflow-hidden bg-background relative">
          {/* 浮动折叠按钮 - 在主内容区域左边缘 */}
          <button
            onClick={() => setSidebarVisible(!sidebarVisible)}
            className={cn(
              "absolute top-1/2 z-50 flex items-center justify-center transition-all duration-200",
              "w-[18px] h-10 rounded-md",
              "bg-card border border-border",
              "text-muted-foreground",
              "hover:text-primary hover:border-primary/30",
              "shadow-[0_2px_6px_rgba(0,0,0,0.08)]",
              sidebarVisible ? "-left-2" : "left-2"
            )}
            style={{ transform: 'translateY(-50%)' }}
            title={sidebarVisible ? "隐藏侧边栏" : "显示侧边栏"}
          >
            {sidebarVisible ? (
              <PanelLeftClose className="h-3 w-3" />
            ) : (
              <PanelLeftOpen className="h-3 w-3" />
            )}
          </button>
          {children}
        </main>
      </div>
    </AppProvider>
  )
}
