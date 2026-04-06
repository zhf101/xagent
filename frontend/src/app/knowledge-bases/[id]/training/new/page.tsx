import { redirect } from "next/navigation"

interface KnowledgeBaseTrainingNewRedirectPageProps {
  params: Promise<{ id: string }>
  searchParams: Promise<{ type?: string }>
}

export default async function KnowledgeBaseTrainingNewRedirectPage({
  params,
  searchParams,
}: KnowledgeBaseTrainingNewRedirectPageProps) {
  const { id } = await params
  const { type } = await searchParams

  if (type === "documentation") {
    redirect(`/knowledge-bases/${id}/training/documentation/new`)
  }

  if (type === "question_sql") {
    redirect(`/knowledge-bases/${id}/training/question-sql/new`)
  }

  redirect(`/knowledge-bases/${id}/training/question-sql`)
}
