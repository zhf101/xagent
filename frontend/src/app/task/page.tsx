"use client";

import { useState, useEffect } from "react";
import { Bot, Presentation, BarChart, Image as ImageIcon, Zap } from "lucide-react";
import { useI18n } from "@/contexts/i18n-context";
import { useApp } from "@/contexts/app-context-chat";
import { ChatStartScreen } from "@/components/chat/ChatStartScreen";
import { apiRequest } from "@/lib/api-wrapper";
import { getApiUrl } from "@/lib/utils";

type DomainMode = "data_generation" | "data_consultation" | "general";

interface PromptCard {
  icon: any;
  title: string;
  description: string;
  prompt: string;
  color: string;
  bg: string;
}

interface RecommendedExample {
  title: string;
  description: string;
  prompt: string;
}

interface RecommendationModePayload {
  recommended_examples: RecommendedExample[];
  confidence: number;
  fallback_needed: boolean;
}

interface RecommendationResponse {
  data_generation: RecommendationModePayload;
  data_consultation: RecommendationModePayload;
  general: RecommendationModePayload;
}

function TaskHomePageContent() {
  const { t } = useI18n();
  const { sendMessage, state, dispatch } = useApp();
  const [files, setFiles] = useState<File[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [domainMode, setDomainMode] = useState<DomainMode>("data_generation");
  const [recommendations, setRecommendations] =
    useState<RecommendationResponse | null>(null);

  // Clear state on mount to ensure we are in "new task" mode
  useEffect(() => {
    dispatch({ type: "RESET_STATE" });
  }, [dispatch]);

  const defaultPromptGroups: Record<DomainMode, PromptCard[]> = {
    general: [
      {
        icon: Presentation,
        title: t("chatPage.cards.general.createPPT.title"),
        description: t("chatPage.cards.general.createPPT.description"),
        prompt: t("chatPage.cards.general.createPPT.prompt"),
        color: "text-orange-400",
        bg: "bg-orange-400/10"
      },
      {
        icon: BarChart,
        title: t("chatPage.cards.general.dataAnalysis.title"),
        description: t("chatPage.cards.general.dataAnalysis.description"),
        prompt: t("chatPage.cards.general.dataAnalysis.prompt"),
        color: "text-blue-400",
        bg: "bg-blue-400/10"
      },
      {
        icon: ImageIcon,
        title: t("chatPage.cards.general.designPoster.title"),
        description: t("chatPage.cards.general.designPoster.description"),
        prompt: t("chatPage.cards.general.designPoster.prompt"),
        color: "text-purple-400",
        bg: "bg-purple-400/10"
      },
      {
        icon: Zap,
        title: t("chatPage.cards.general.automatic.title"),
        description: t("chatPage.cards.general.automatic.description"),
        prompt: t("chatPage.cards.general.automatic.prompt"),
        color: "text-green-400",
        bg: "bg-green-400/10"
      }
    ],
    data_generation: [
      {
        icon: BarChart,
        title: t("chatPage.cards.dataGeneration.orders.title"),
        description: t("chatPage.cards.dataGeneration.orders.description"),
        prompt: t("chatPage.cards.dataGeneration.orders.prompt"),
        color: "text-blue-400",
        bg: "bg-blue-400/10"
      },
      {
        icon: Presentation,
        title: t("chatPage.cards.dataGeneration.transactions.title"),
        description: t("chatPage.cards.dataGeneration.transactions.description"),
        prompt: t("chatPage.cards.dataGeneration.transactions.prompt"),
        color: "text-cyan-400",
        bg: "bg-cyan-400/10"
      },
      {
        icon: Zap,
        title: t("chatPage.cards.dataGeneration.edgeCases.title"),
        description: t("chatPage.cards.dataGeneration.edgeCases.description"),
        prompt: t("chatPage.cards.dataGeneration.edgeCases.prompt"),
        color: "text-amber-400",
        bg: "bg-amber-400/10"
      },
      {
        icon: ImageIcon,
        title: t("chatPage.cards.dataGeneration.multiTable.title"),
        description: t("chatPage.cards.dataGeneration.multiTable.description"),
        prompt: t("chatPage.cards.dataGeneration.multiTable.prompt"),
        color: "text-emerald-400",
        bg: "bg-emerald-400/10"
      }
    ],
    data_consultation: [
      {
        icon: Presentation,
        title: t("chatPage.cards.dataConsultation.templateUsage.title"),
        description: t("chatPage.cards.dataConsultation.templateUsage.description"),
        prompt: t("chatPage.cards.dataConsultation.templateUsage.prompt"),
        color: "text-orange-400",
        bg: "bg-orange-400/10"
      },
      {
        icon: BarChart,
        title: t("chatPage.cards.dataConsultation.assetChoice.title"),
        description: t("chatPage.cards.dataConsultation.assetChoice.description"),
        prompt: t("chatPage.cards.dataConsultation.assetChoice.prompt"),
        color: "text-blue-400",
        bg: "bg-blue-400/10"
      },
      {
        icon: ImageIcon,
        title: t("chatPage.cards.dataConsultation.assetDifference.title"),
        description: t("chatPage.cards.dataConsultation.assetDifference.description"),
        prompt: t("chatPage.cards.dataConsultation.assetDifference.prompt"),
        color: "text-purple-400",
        bg: "bg-purple-400/10"
      },
      {
        icon: Zap,
        title: t("chatPage.cards.dataConsultation.failureReason.title"),
        description: t("chatPage.cards.dataConsultation.failureReason.description"),
        prompt: t("chatPage.cards.dataConsultation.failureReason.prompt"),
        color: "text-green-400",
        bg: "bg-green-400/10"
      }
    ],
  };

  useEffect(() => {
    let cancelled = false;

    const loadRecommendations = async () => {
      try {
        const response = await apiRequest(`${getApiUrl()}/api/recommendations/task-prompts`);
        if (!response.ok) return;
        const data = (await response.json()) as RecommendationResponse;
        if (!cancelled) {
          setRecommendations(data);
        }
      } catch {
        if (!cancelled) {
          setRecommendations(null);
        }
      }
    };

    loadRecommendations();

    return () => {
      cancelled = true;
    };
  }, []);

  const mergePromptCards = (mode: DomainMode): PromptCard[] => {
    const defaults = defaultPromptGroups[mode];
    const personalized = recommendations?.[mode]?.recommended_examples || [];
    const usedPrompts = new Set<string>();

    const personalizedCards = personalized.slice(0, 4).map((item, index) => {
      usedPrompts.add(item.prompt);
      const fallbackCard = defaults[index] || defaults[0];
      return {
        ...fallbackCard,
        title: item.title,
        description: item.description,
        prompt: item.prompt,
      };
    });

    const fallbackCards = defaults.filter((item) => !usedPrompts.has(item.prompt));
    return [...personalizedCards, ...fallbackCards].slice(0, 4);
  };

  const samplePrompts = mergePromptCards(domainMode);

  const handleSend = async (message: string, filesToSend: File[], config?: any) => {
    if (state.isProcessing) return;

    // Use sendMessage from AppContext - it will create task and send files via WebSocket
    await sendMessage(message, config, filesToSend || files);

    // Clear files after sending
    setFiles([]);
    setInputValue("");
  };

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto">
        <main className="container max-w-4xl mx-auto px-4 py-8">
          <ChatStartScreen
            title={t("chatPage.page.emptyTitle")}
            description={t("chatPage.page.emptyDescription", { appName: process.env.NEXT_PUBLIC_APP_NAME || "Xagent" })}
            icon={<Bot className="w-10 h-10 text-[hsl(var(--gradient-from))]" />}
            prompts={samplePrompts}
            onSend={handleSend}
            isSending={state.isProcessing}
            files={files}
            onFilesChange={setFiles}
            inputValue={inputValue}
            onInputChange={setInputValue}
            showModeToggle={true}
            domainMode={domainMode}
            onDomainModeChange={setDomainMode}
          />
        </main>
      </div>
    </div>
  );
}

export default TaskHomePageContent;
