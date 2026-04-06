import { redirect } from "next/navigation"

interface KnowledgeBaseTrainingPageProps {
  params: Promise<{ id: string }>
}

export default async function KnowledgeBaseTrainingPage({
  params,
}: KnowledgeBaseTrainingPageProps) {
  const { id } = await params
  redirect(`/knowledge-bases/${id}/training/question-sql`)
}
