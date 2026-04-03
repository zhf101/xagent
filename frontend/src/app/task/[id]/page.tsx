"use client";

import React, { useState, useRef, useEffect, Suspense, useCallback, useMemo } from "react";
import { GitMerge, ArrowLeft, Loader2, FolderOpen, ShieldAlert, Play } from "lucide-react";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { ChatInput } from "@/components/chat/ChatInput";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useApp, type TaskApprovalSummary } from "@/contexts/app-context-chat";
import { useI18n } from "@/contexts/i18n-context";
import { useParams, useRouter } from "next/navigation"
import { PreviewSheet } from "@/components/preview-sheet";
import { FilePreviewContent } from "@/components/file/file-preview-content";
import { TokenUsageDisplay } from "@/components/chat/TokenUsageDisplay";
import { TaskFileManager } from "@/components/file/task-file-manager";
import { getApiUrl } from "@/lib/utils";
import { apiRequest } from "@/lib/api-wrapper";
import dagre from "dagre"
import { CenterPanel } from "@/components/layout/center-panel"
import { FilePreviewActionButtons } from "@/components/file/file-preview-action-buttons"
import { toast } from "sonner";

function formatApprovalStatus(status?: string | null) {
  switch (status) {
    case "pending":
      return "等待审批"
    case "approved":
      return "已审批"
    case "rejected":
      return "已拒绝"
    default:
      return "未触发"
  }
}

function formatRiskLevel(level?: string | null) {
  switch (level) {
    case "critical":
      return "Critical"
    case "high":
      return "High"
    case "medium":
      return "Medium"
    case "low":
      return "Low"
    default:
      return level || "Unknown"
  }
}

function getApprovalStatusVariant(status?: string | null): "secondary" | "outline" | "destructive" | "default" {
  switch (status) {
    case "approved":
      return "default"
    case "rejected":
      return "destructive"
    case "pending":
      return "secondary"
    default:
      return "outline"
  }
}

function getRiskVariant(level?: string | null): "secondary" | "outline" | "destructive" | "default" {
  switch (level) {
    case "critical":
    case "high":
      return "destructive"
    case "medium":
      return "secondary"
    case "low":
      return "default"
    default:
      return "outline"
  }
}

function formatLocalTimestamp(value?: string | number | null) {
  if (!value) return "未记录"
  const timestamp = typeof value === "number" ? value : new Date(value).getTime()
  if (!Number.isFinite(timestamp)) return String(value)
  return new Date(timestamp).toLocaleString()
}

function TaskApprovalCard({
  approval,
  taskStatus,
  onResume,
  isResuming,
}: {
  approval?: TaskApprovalSummary
  taskStatus?: string
  onResume: () => Promise<void>
  isResuming: boolean
}) {
  const activeRequest =
    approval?.pending_request ||
    approval?.approved_request ||
    approval?.latest_request

  if (
    !approval ||
    (
      !approval.blocked_step_id &&
      !approval.pending_request &&
      !approval.approved_request &&
      !approval.latest_request &&
      !approval.last_resume_at
    )
  ) {
    return null
  }

  const requestStatus = activeRequest?.status || (approval.can_resume ? "approved" : undefined)
  const riskReasons = activeRequest?.risk_reasons || []
  const sqlPreview = activeRequest?.sql_original?.trim()

  let headline = "SQL 审批状态"
  let description = "当前任务包含需要审批的 SQL 工具调用。"

  if (taskStatus === "waiting_approval" && requestStatus === "pending") {
    headline = "等待 SQL 审批"
    description = "DAG 已在高风险 SQL 步骤处中断，等待审批人处理后才能继续。"
  } else if (approval.can_resume) {
    headline = "审批已通过，可继续执行"
    description = "审批结果已落库。重新进入任务页后，仍可从当前快照继续向下恢复 DAG。"
  } else if (requestStatus === "rejected" || taskStatus === "failed") {
    headline = "审批被拒绝"
    description = "本次高风险 SQL 调用未获批准，任务已停止在当前审批节点。"
  } else if (approval.last_resume_at) {
    description = "该任务曾在审批后恢复执行，以下保留的是最近一次审批快照。"
  }

  return (
    <Card className="mb-4 border-amber-500/30 bg-amber-500/5">
      <CardHeader className="gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldAlert className="h-4 w-4 text-amber-600" />
              {headline}
            </CardTitle>
            <CardDescription>{description}</CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={getApprovalStatusVariant(requestStatus)}>
              {formatApprovalStatus(requestStatus)}
            </Badge>
            <Badge variant={getRiskVariant(activeRequest?.risk_level)}>
              Risk {formatRiskLevel(activeRequest?.risk_level)}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 text-sm md:grid-cols-2">
          <div className="rounded-lg border bg-background/80 p-3">
            <div className="text-xs text-muted-foreground">阻塞步骤</div>
            <div className="mt-1 font-medium">{approval.blocked_step_id || "未记录"}</div>
          </div>
          <div className="rounded-lg border bg-background/80 p-3">
            <div className="text-xs text-muted-foreground">动作类型</div>
            <div className="mt-1 font-medium">{approval.blocked_action_type || activeRequest?.approval_type || "sql_execute"}</div>
          </div>
          <div className="rounded-lg border bg-background/80 p-3">
            <div className="text-xs text-muted-foreground">数据源</div>
            <div className="mt-1 font-medium">{activeRequest?.datasource_id || "未记录"}</div>
          </div>
          <div className="rounded-lg border bg-background/80 p-3">
            <div className="text-xs text-muted-foreground">审批单号</div>
            <div className="mt-1 font-medium">{approval.approval_request_id || "未生成"}</div>
          </div>
          <div className="rounded-lg border bg-background/80 p-3">
            <div className="text-xs text-muted-foreground">最近审批时间</div>
            <div className="mt-1 font-medium">
              {formatLocalTimestamp(activeRequest?.approved_at || activeRequest?.updated_at)}
            </div>
          </div>
          <div className="rounded-lg border bg-background/80 p-3">
            <div className="text-xs text-muted-foreground">最近恢复时间</div>
            <div className="mt-1 font-medium">{formatLocalTimestamp(approval.last_resume_at)}</div>
          </div>
        </div>

        {riskReasons.length > 0 && (
          <div className="rounded-lg border bg-background/80 p-3">
            <div className="text-xs text-muted-foreground">风险原因</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {riskReasons.map((reason, index) => (
                <Badge key={`${reason}-${index}`} variant="outline" className="max-w-full whitespace-normal py-1 text-left">
                  {reason}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {sqlPreview && (
          <div className="rounded-lg border bg-background/80 p-3">
            <div className="text-xs text-muted-foreground">SQL 预览</div>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted/40 p-3 text-xs text-foreground/90">
              {sqlPreview}
            </pre>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs text-muted-foreground">
            快照版本 {approval.snapshot_version ?? "-"} · 全局迭代 {approval.global_iteration ?? "-"}
          </div>
          {approval.can_resume && (
            <Button onClick={onResume} disabled={isResuming} className="gap-2">
              {isResuming ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              审批通过后继续执行
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function TaskDetailContent() {
  const { state, sendMessage, setTaskId, openFilePreview, closeFilePreview, requestStatus, dispatch, pauseTask, resumeTask } = useApp();
  const { t } = useI18n();
  const [files, setFiles] = useState<File[]>([]);
  const [isResumingApproval, setIsResumingApproval] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const params = useParams();
  const router = useRouter();
  const taskIdFromUrl = params.id;

  // DAG preview toggle and layout
  const [dagPreviewOpen, setDagPreviewOpen] = useState(false);
  const [dagLayout, setDagLayout] = useState<'TB' | 'LR'>('TB');
  const anyPreviewOpen = state.filePreview.isOpen || dagPreviewOpen;

  const [leftWidth, setLeftWidth] = useState(50);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const leftWidthRef = useRef(50);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging || !containerRef.current) return;
    const containerRect = containerRef.current.getBoundingClientRect();
    let newLeftWidth = ((e.clientX - containerRect.left) / containerRect.width) * 100;
    if (newLeftWidth < 20) newLeftWidth = 20;
    if (newLeftWidth > 80) newLeftWidth = 80;
    setLeftWidth(newLeftWidth);
    leftWidthRef.current = newLeftWidth;
  }, [isDragging]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  useEffect(() => {
    if (isDragging) {
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      window.addEventListener('mousemove', handleMouseMove, { passive: true });
      window.addEventListener('mouseup', handleMouseUp);
    } else {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    }
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  useEffect(() => {
    if (taskIdFromUrl && typeof taskIdFromUrl === 'string') {
      const taskIdNum = parseInt(taskIdFromUrl, 10);
      if (!isNaN(taskIdNum) && taskIdNum !== state.taskId) {
        console.log('🔄 Setting taskId from URL:', taskIdNum);
        setTaskId(taskIdNum);
      }
    }
  }, [taskIdFromUrl, setTaskId, state.taskId]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [state.messages, state.steps]);

  useEffect(() => {
    if (state.filePreview.isOpen) {
      setDagPreviewOpen(false);
    }
  }, [state.filePreview.isOpen]);

  useEffect(() => {
    const handleFilePreviewEvent = (event: Event) => {
      const { filePath, fileName, allFiles, currentIndex } = (event as CustomEvent<any>).detail || {};
      if (!filePath) return;
      if (Array.isArray(allFiles) && allFiles.length > 0) {
        openFilePreview(filePath, fileName, allFiles, typeof currentIndex === 'number' ? currentIndex : 0);
      } else {
        openFilePreview(filePath, fileName);
      }
    };
    window.addEventListener('openFilePreview', handleFilePreviewEvent as EventListener);
    return () => {
      window.removeEventListener('openFilePreview', handleFilePreviewEvent as EventListener);
    };
  }, [openFilePreview]);

  // Close file preview when leaving the task page
  useEffect(() => {
    return () => {
      closeFilePreview();
    };
  }, [closeFilePreview]);

  const handleDownload = async () => {
    try {
      if (!state.filePreview.fileId) return;

      const response = await apiRequest(`${getApiUrl()}/api/files/download/${state.filePreview.fileId}`);

      if (!response.ok) {
        throw new Error(`Download failed: ${response.statusText}`);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = state.filePreview.fileName || 'download';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Failed to download file:', error);
    }
  };

  const handleSend = async (message: string, config?: any, filesToSend?: File[]) => {
    await sendMessage(message, config, filesToSend || files);
    setFiles([]);
  };

  // Only keep user messages and final assistant messages in timeline
  type CombinedItem = {
    id: string;
    role: "user" | "assistant";
    content: string | React.ReactNode;
    rawContent?: string;
    timestamp: number;
    traceEvents?: any[];
  };
  const combinedItems: CombinedItem[] = useMemo(() => {
    const toTime = (ts: any): number => {
      let time: number;
      if (typeof ts === 'number') {
        time = ts;
      } else {
        const n = Number(ts);
        if (!isNaN(n)) {
          time = n;
        } else {
          time = new Date(ts).getTime();
        }
      }

      if (time < 100000000000) {
        return time * 1000;
      }
      return time;
    };

    const msgItems: CombinedItem[] = state.messages
      .filter((m) => m.role === 'user' || m.isResult)
      .map((m) => ({
        id: m.id || `${m.role}-${toTime(m.timestamp)}`,
        role: m.role,
        content: m.content,
        rawContent: m.rawContent,
        timestamp: toTime(m.timestamp),
        traceEvents: m.traceEvents,
      }));

    const merged = msgItems;
    merged.sort((a, b) => a.timestamp - b.timestamp);
    return merged;
  }, [state.messages]);

  // DAG node and edge calculation
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setGraph({
    rankdir: dagLayout === 'LR' ? 'LR' : 'TB',
    nodesep: 80,
    ranksep: 100,
    marginx: 20,
    marginy: 20,
  });
  dagreGraph.setDefaultEdgeLabel(() => '');

  const validSteps = state.steps.filter(step => step && typeof step.id === 'string' && step.id.trim() !== '');

  // Set nodes
  validSteps.forEach((step, index) => {
    try {
      dagreGraph.setNode(step.id, {
        label: step.name || `Step ${index + 1}`,
        width: 250,
        height: 200,
      });
    } catch (error) {
      console.error('Error adding node to dagre:', step, error);
    }
  });

  // Set edges
  validSteps.forEach((step) => {
    if (!step.dependencies || !Array.isArray(step.dependencies)) {
      return;
    }
    step.dependencies.forEach(depId => {
      if (!depId || typeof depId !== 'string' || depId.trim() === '') {
        return;
      }
      const depStep = validSteps.find(s => s.id === depId);
      if (depStep) {
        try {
          dagreGraph.setEdge(depId, step.id, {});
        } catch (error) {
          console.error('Error adding edge to dagre:', `${depId} -> ${step.id}`, error);
        }
      }
    });
  });

  let dagreLayoutSuccessful = true;
  try {
    dagre.layout(dagreGraph);
  } catch (error) {
    console.error('Dagre layout failed:', error);
    dagreLayoutSuccessful = false;
  }

  const dagNodes = state.steps.map((step, index) => {
    let node: any, safeNode: any;
    if (!step.id || typeof step.id !== 'string' || step.id.trim() === '') {
      safeNode = { x: (index % 3) * 300, y: Math.floor(index / 3) * 250 };
    } else if (dagreLayoutSuccessful) {
      try {
        node = dagreGraph.node(step.id);
        safeNode = typeof node === 'object' && node !== null ? node : { x: (index % 3) * 300, y: Math.floor(index / 3) * 250 };
      } catch (error) {
        safeNode = { x: (index % 3) * 300, y: Math.floor(index / 3) * 250 };
      }
    } else {
      safeNode = { x: (index % 3) * 300, y: Math.floor(index / 3) * 250 };
    }
    return {
      id: step.id || `step-${index}`,
      type: "default",
      position: { x: (safeNode.x || 0) - 125, y: (safeNode.y || 0) - 100 },
      data: {
        label: step.name || `Step ${index + 1}`,
        status: step.status,
        description: step.description,
        tool_names: step.tool_names,
        started_at: step.started_at,
        completed_at: step.completed_at,
        result: step.result_data,
        conditional_branches: step.conditional_branches,
        required_branch: step.required_branch,
        is_conditional: step.is_conditional,
      },
    };
  });

  const dagEdges: any[] = [];
  const validNodeIds = new Set(validSteps.map(s => s.id));
  if (dagreLayoutSuccessful) {
    validSteps.forEach((step) => {
      if (!step.dependencies || !Array.isArray(step.dependencies)) {
        return;
      }
      step.dependencies.forEach(depId => {
        if (!depId || typeof depId !== 'string' || depId.trim() === '') {
          return;
        }
        if (validNodeIds.has(depId) && validNodeIds.has(step.id)) {
          const edge = {
            id: `${depId}-${step.id}`,
            source: depId,
            target: step.id,
            data: {}
          };
          dagEdges.push(edge);
        }
      });
    });
  }

  const hasFinalAssistantMessage =
    combinedItems.length > 0 &&
    combinedItems[combinedItems.length - 1].role === "assistant";

  const isPlanning = dagNodes.length === 0 && state.dagExecution?.phase === "planning";
  const hasError = dagNodes.length === 0 && (state.dagExecution?.phase === "failed" || state.currentTask?.status === "failed");
  const approvalSummary = state.currentTask?.approval;

  const handleResumeApproved = useCallback(async () => {
    if (!state.taskId) return;

    setIsResumingApproval(true);
    try {
      const response = await apiRequest(`${getApiUrl()}/api/chat/task/${state.taskId}/resume-approved`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload?.detail || response.statusText || "Resume failed");
      }

      if (payload?.resumed) {
        toast.success("DAG 已恢复执行");
      } else {
        toast.error("当前审批状态还不能恢复执行");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Resume failed";
      toast.error(`恢复执行失败: ${message}`);
    } finally {
      setIsResumingApproval(false);
    }
  }, [state.taskId]);

  return (
    <div
      ref={containerRef}
      className={`h-screen bg-background relative transition-all flex ${anyPreviewOpen ? 'flex-row items-stretch' : 'flex-col'} overflow-hidden`}
    >
      {/* Back Button - Only show if this task is from an agent */}
      {state.currentTask?.agentId && (
        <div className="absolute top-4 left-4 z-50">
          <Button
            variant="ghost"
            size="icon"
            className="rounded-full bg-background/50 hover:bg-background/80 backdrop-blur border shadow-sm"
            onClick={() => {
              const agentId = state.currentTask?.agentId;
              if (agentId) {
                router.push(`/agent/${agentId}`);
              } else {
                router.push("/task");
              }
            }}
            title={t("common.back")}
          >
            <ArrowLeft className="w-5 h-5" />
          </Button>
        </div>
      )}

      {/* Left Panel */}
      <div
        style={{ width: anyPreviewOpen ? `${leftWidth}%` : '100%' }}
        className={`${anyPreviewOpen ? '' : 'flex-1'} min-w-0 flex flex-col min-h-0 transition-[width] duration-0 relative`}
      >
        {/* Messages scroll area */}
        <div className="flex-1 overflow-y-auto">
          <main className={`container max-w-4xl mx-auto px-4 py-8 relative z-0 transition-all`}>
            <div className="space-y-6 pb-4">
              {state.isHistoryLoading ? (
                <div className="flex flex-col items-center justify-center min-h-[60vh] py-16 text-center">
                  <div className="relative mb-6">
                    <div className="w-16 h-16 rounded-2xl bg-muted/30 flex items-center justify-center animate-pulse">
                      <Loader2 className="w-8 h-8 text-primary animate-spin" />
                    </div>
                  </div>
                  <h2 className="text-xl font-medium mb-2 text-foreground/80">
                    {t("common.loading")}
                  </h2>
                </div>
              ) : (
                <>
                  {combinedItems.map((item) => (
                    <ChatMessage
                      key={item.id}
                      role={item.role}
                      content={item.content}
                      rawContent={item.rawContent}
                      traceEvents={item.traceEvents as any || []}
                      showProcessView={true}
                      timestamp={item.timestamp}
                    />
                  ))}

                  {(state.isProcessing || (state.traceEvents?.length || 0) > 0 || state.currentTask?.status === 'paused' || state.currentTask?.status === 'waiting_approval') && !hasFinalAssistantMessage && (
                    <ChatMessage
                      role="assistant"
                      content={null}
                      traceEvents={state.traceEvents as any || []}
                      showProcessView={true}
                      isVirtual
                      taskStatus={state.currentTask?.status}
                    />
                  )}
                </>
              )}
              <div ref={messagesEndRef} />
            </div>
          </main>
        </div>

        {/* Fixed input box at bottom */}
        <div className="flex-shrink-0 z-10 glass pb-6">
          <div className="container max-w-4xl mx-auto px-4">
            <TaskApprovalCard
              approval={approvalSummary}
              taskStatus={state.currentTask?.status}
              onResume={handleResumeApproved}
              isResuming={isResumingApproval}
            />

            <div className="mb-4 flex items-center">
              {state.currentTask?.isDag !== false && (
                <div
                  className="inline-flex items-center gap-1 rounded-xl border bg-card/80 backdrop-blur p-2 cursor-pointer hover:bg-muted/30 transition-colors text-sm"
                  onClick={() => {
                    closeFilePreview();
                    setDagPreviewOpen(true);
                  }}
                  title={t("chatPage.executionPlan.title")}
                >
                  <GitMerge className="w-3.5 h-3.5" />
                  {t("chatPage.executionPlan.title")}
                </div>
              )}

              <TaskFileManager
                taskId={state.taskId}
                onPreview={(fileId, fileName) => openFilePreview(fileId, fileName)}
              >
                <div
                  className="ml-2 inline-flex items-center gap-1 rounded-xl border bg-card/80 backdrop-blur p-2 cursor-pointer hover:bg-muted/30 transition-colors text-sm"
                  title={t("files.header.title")}
                >
                  <FolderOpen className="w-3.5 h-3.5" />
                  {t("files.header.title")}
                </div>
              </TaskFileManager>

              <div className="ml-auto">
                <TokenUsageDisplay
                  taskId={state.taskId}
                  isRunning={state.currentTask?.status === 'running'}
                />
              </div>
            </div>

            <ChatInput
              onSend={handleSend}
              isLoading={state.isProcessing}
              files={files}
              onFilesChange={setFiles}
              showModeToggle={false}
              taskStatus={state.currentTask?.status}
              onPause={pauseTask}
              onResume={resumeTask}
              taskConfig={state.currentTask ? {
                model: state.currentTask.modelId || state.currentTask.modelName,
                smallFastModel: state.currentTask.smallFastModelId,
                visualModel: state.currentTask.visualModelId,
                compactModel: state.currentTask.compactModelId
              } : undefined}
              readOnlyConfig={true}
            />
          </div>
        </div>
      </div>

      {/* Divider */}
      {anyPreviewOpen && (
        <div
          onMouseDown={handleMouseDown}
          className={`relative w-1 cursor-col-resize group z-[100] flex-shrink-0 hover:bg-primary/20 active:bg-primary/40 transition-colors ${isDragging ? 'bg-primary/40' : 'bg-transparent'}`}
        >
          <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-[1px] bg-border group-hover:bg-primary group-hover:w-[2px] transition-all" />
          <div className="absolute inset-y-0 -left-2 -right-2" />
        </div>
      )}

      {/* Right Panel */}
      {anyPreviewOpen && (
        <div
          style={{ width: `${100 - leftWidth}%`, pointerEvents: isDragging ? 'none' : 'auto' }}
          className="flex-shrink-0 px-2 py-6 overflow-hidden relative"
        >
          <PreviewSheet
            open={state.filePreview.isOpen || dagPreviewOpen}
            onOpenChange={(open) => {
              if (!open) {
                closeFilePreview();
                setDagPreviewOpen(false);
              }
            }}
            title={
              state.filePreview.isOpen ? <>{state.filePreview.fileName}</> :
              t("chatPage.executionPlan.title")
            }
            actions={state.filePreview.isOpen ? (
              <FilePreviewActionButtons
                viewMode={state.filePreview.viewMode}
                onViewModeChange={(mode) => dispatch({ type: 'SET_FILE_PREVIEW_MODE', payload: mode })}
                fileName={state.filePreview.fileName || ''}
                onDownload={handleDownload}
                showText={true}
              />
            ) : null}
          >
            <div className="w-full h-full">
              {state.filePreview.isOpen ? (
                <FilePreviewContent open={state.filePreview.isOpen} />
              ) : (
                <CenterPanel
                  dagExecution={state.dagExecution}
                  dagNodes={dagNodes}
                  dagEdges={dagEdges as any}
                  dagLayout={dagLayout}
                  onLayoutChange={setDagLayout}
                  isPlanning={isPlanning}
                  hasError={hasError}
                  currentTaskStatus={state.currentTask?.status}
                  onRefresh={() => requestStatus()}
                  onFileClick={openFilePreview}
                />
              )}
            </div>
          </PreviewSheet>
        </div>
      )}

      {/* Drag overlay */}
      {isDragging && <div className="fixed inset-0 z-[99] cursor-col-resize" />}
    </div>
  );
}

export default function TaskDetailPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-screen"><Loader2 className="w-8 h-8 animate-spin" /></div>}>
      <TaskDetailContent />
    </Suspense>
  );
}
