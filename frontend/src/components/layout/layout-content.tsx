"use client"

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/layout/sidebar";
import { AppProvider } from "@/contexts/app-context-chat";
import { useAuth } from "@/contexts/auth-context";
import { isAuthPublicPath } from "@/lib/auth-pages";
import { cn } from "@/lib/utils";
import { useEffect, useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

const SIDEBAR_VISIBLE_KEY = "xagent.sidebar.visible";

interface LayoutContentProps {
  children: React.ReactNode;
}

export function LayoutContent({ children }: LayoutContentProps) {
  const pathname = usePathname();
  const { token } = useAuth();
  const isAuthPage = isAuthPublicPath(pathname);
  const [sidebarVisible, setSidebarVisible] = useState(true);

  // 在浏览器端持久化侧边栏显隐状态，避免用户每次刷新后都要重新展开或收起。
  useEffect(() => {
    try {
      const savedVisible = window.localStorage.getItem(SIDEBAR_VISIBLE_KEY);
      if (savedVisible !== null) {
        setSidebarVisible(savedVisible === "1");
      }
    } catch {
      // 本地存储不可用时退回默认显示，避免影响页面主流程。
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        SIDEBAR_VISIBLE_KEY,
        sidebarVisible ? "1" : "0"
      );
    } catch {
      // 忽略持久化失败，保持当前内存态即可。
    }
  }, [sidebarVisible]);

  if (isAuthPage) {
    // For auth pages, just render children without sidebar
    return <>{children}</>;
  }

  // For other pages, show sidebar and main layout
  return (
    <AppProvider token={token || undefined}>
      <div className="flex h-screen bg-background relative">
        {sidebarVisible && <Sidebar />}
        <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-background">
          <button
            type="button"
            onClick={() => setSidebarVisible((visible) => !visible)}
            aria-label={sidebarVisible ? "隐藏侧边栏" : "显示侧边栏"}
            title={sidebarVisible ? "隐藏侧边栏" : "显示侧边栏"}
            className={cn(
              "absolute top-1/2 z-50 flex h-10 w-[18px] items-center justify-center rounded-md border border-border bg-card text-muted-foreground shadow-[0_2px_6px_rgba(0,0,0,0.08)] transition-all duration-200",
              "hover:border-primary/30 hover:text-primary",
              sidebarVisible ? "-left-2" : "left-2"
            )}
            style={{ transform: "translateY(-50%)" }}
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
  );
}
