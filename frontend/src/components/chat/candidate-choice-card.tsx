import React, { useMemo, useState } from "react"
import { Play, Search, GitBranch, Layers } from "lucide-react"

import { ClarificationForm } from "@/components/chat/clarification-form"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { useApp, type Interaction } from "@/contexts/app-context-chat"

interface CandidateChoiceCardProps {
  message: string
  candidates: Array<{
    source_type?: string
    candidate_id?: string
    display_name?: string
    score?: number
    matched_signals?: string[]
    summary?: string
  }>
  interactions?: Interaction[]
  messageId: string
}

const DIRECT_EXECUTE_STRATEGY_BY_SOURCE: Record<string, string> = {
  template: "template_direct",
  legacy_scenario: "legacy_direct",
}

const PROBE_SUPPORTED_SOURCES = new Set(["template", "sql_asset", "http_asset"])

export function CandidateChoiceCard({
  message,
  candidates,
  interactions,
  messageId,
}: CandidateChoiceCardProps) {
  const {
    state,
    sendExecuteDirect,
    sendProbeRequest,
    sendConversationUpdate,
  } = useApp()
  const [pendingAction, setPendingAction] = useState<string | null>(null)

  const factSnapshot = (state.conversationInfo?.factSnapshot ||
    {}) as Record<string, unknown>
  const isTaskRunning = state.currentTask?.status === "running"

  const candidateCards = useMemo(() => candidates || [], [candidates])

  const handleDirectExecute = async (
    sourceType: string,
    candidateId: string,
  ) => {
    const strategy = DIRECT_EXECUTE_STRATEGY_BY_SOURCE[sourceType]
    if (!strategy) return
    setPendingAction(`execute:${candidateId}`)
    try {
      const normalizedCandidateId =
        sourceType === "legacy_scenario" && !candidateId.startsWith("legacy:")
          ? `legacy:${candidateId}`
          : candidateId
      await sendExecuteDirect(strategy, normalizedCandidateId, factSnapshot)
    } finally {
      setPendingAction(null)
    }
  }

  const handleProbe = async (sourceType: string, candidateId: string) => {
    setPendingAction(`probe:${candidateId}`)
    try {
      await sendProbeRequest(sourceType, candidateId, factSnapshot, "preview")
    } finally {
      setPendingAction(null)
    }
  }

  const handleContinuePlanning = async (
    sourceType: string,
    candidateId: string,
  ) => {
    setPendingAction(`plan:${candidateId}`)
    try {
      await sendConversationUpdate({
        reuse_strategy: `reuse:${sourceType}`,
        selected_candidate_id: candidateId,
        selected_source_type: sourceType,
      })
    } finally {
      setPendingAction(null)
    }
  }

  const handleScratch = async () => {
    setPendingAction("scratch")
    try {
      await sendConversationUpdate({
        reuse_strategy: "scratch",
        selected_candidate_id: null,
        selected_source_type: null,
      })
    } finally {
      setPendingAction(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="text-sm leading-6">{message}</div>
      <div className="text-xs text-muted-foreground">
        你可以直接执行候选、先试跑验证，或基于某个候选继续规划。
      </div>

      {candidateCards.length > 0 ? (
        <div className="grid gap-3">
          {candidateCards.map((candidate, index) => {
            const sourceType = String(candidate.source_type || "")
            const candidateId = String(candidate.candidate_id || "")
            const canDirectExecute = Boolean(
              DIRECT_EXECUTE_STRATEGY_BY_SOURCE[sourceType] && candidateId,
            )
            const canProbe = Boolean(
              PROBE_SUPPORTED_SOURCES.has(sourceType) && candidateId,
            )

            return (
              <div
                key={`${candidateId || index}`}
                className="rounded-xl border border-border/60 bg-card/60 px-4 py-4 space-y-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">
                    {candidate.display_name || "未命名候选"}
                  </span>
                  {sourceType ? <Badge variant="secondary">{sourceType}</Badge> : null}
                  {candidate.score != null ? (
                    <Badge variant="outline">
                      score {String(candidate.score)}
                    </Badge>
                  ) : null}
                </div>

                {candidate.summary ? (
                  <div className="text-xs text-muted-foreground leading-5">
                    {candidate.summary}
                  </div>
                ) : null}

                {Array.isArray(candidate.matched_signals) &&
                candidate.matched_signals.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {candidate.matched_signals.map((signal) => (
                      <Badge
                        key={signal}
                        variant="outline"
                        className="text-[10px]"
                      >
                        {signal}
                      </Badge>
                    ))}
                  </div>
                ) : null}

                <div className="flex flex-wrap gap-2">
                  {canDirectExecute ? (
                    <Button
                      size="sm"
                      disabled={isTaskRunning || !!pendingAction}
                      onClick={() => handleDirectExecute(sourceType, candidateId)}
                    >
                      <Play className="mr-1 h-3.5 w-3.5" />
                      {pendingAction === `execute:${candidateId}`
                        ? "执行中..."
                        : "直接执行"}
                    </Button>
                  ) : null}

                  {canProbe ? (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={isTaskRunning || !!pendingAction}
                      onClick={() => handleProbe(sourceType, candidateId)}
                    >
                      <Search className="mr-1 h-3.5 w-3.5" />
                      {pendingAction === `probe:${candidateId}`
                        ? "试跑中..."
                        : "试跑验证"}
                    </Button>
                  ) : null}

                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={isTaskRunning || !!pendingAction}
                    onClick={() => handleContinuePlanning(sourceType, candidateId)}
                  >
                    <GitBranch className="mr-1 h-3.5 w-3.5" />
                    {pendingAction === `plan:${candidateId}`
                      ? "处理中..."
                      : "基于此继续规划"}
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      ) : null}

      <div className="rounded-lg border border-dashed border-border/60 p-3 space-y-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Layers className="h-4 w-4" />
          <span>不复用任何候选</span>
        </div>
        <div className="text-xs text-muted-foreground">
          直接进入从零规划，让系统基于当前事实集重新决策。
        </div>
        <div>
          <Button
            size="sm"
            variant="outline"
            disabled={isTaskRunning || !!pendingAction}
            onClick={handleScratch}
          >
            {pendingAction === "scratch" ? "处理中..." : "从零规划"}
          </Button>
        </div>
      </div>

      {interactions && interactions.length > 0 ? (
        <ClarificationForm interactions={interactions} messageId={messageId} />
      ) : null}
    </div>
  )
}
