import { redirect } from "next/navigation"

export default function KnowledgeBaseReviewPage({
  params,
}: {
  params: { id: string }
}) {
  redirect(`/gdp/vanna/knowledge-bases/${params.id}/training`)
}
