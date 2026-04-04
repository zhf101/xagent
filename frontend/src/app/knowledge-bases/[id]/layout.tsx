import type { ReactNode } from "react"

import { KnowledgeBaseLayout } from "@/components/gdp/vanna/knowledge-base-layout"

export default function KnowledgeBaseDetailLayout({
  children,
}: {
  children: ReactNode
}) {
  return <KnowledgeBaseLayout>{children}</KnowledgeBaseLayout>
}
