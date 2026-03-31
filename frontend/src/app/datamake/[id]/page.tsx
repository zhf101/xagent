"use client"

import React from "react"
import { useParams } from "next/navigation"
import { DataMakeChatSidebar } from "../../../components/datamake/chat-sidebar/datamake-chat-sidebar"
import { FlowDraftCanvas } from "../../../components/datamake/flow-canvas/flowdraft-canvas"
import { ContextDrawer } from "../../../components/datamake/context-drawer/context-drawer"

export default function DataMakePage() {
  const params = useParams()
  const taskId = params.id ? parseInt(params.id as string, 10) : undefined

  return (
    <div className="flex h-screen w-full bg-white overflow-hidden text-slate-800">
      {/* 1. 左侧对话框：核心业务澄清和阻断流转 */}
      <DataMakeChatSidebar taskId={taskId} />

      {/* 2. 中间主工作区：DAG 编排画布 */}
      <FlowDraftCanvas />
      
      {/* 3. 右侧审计区：Memory Plane 数据与执行详情 */}
      <ContextDrawer taskId={taskId} />
    </div>
  )
}
