import { redirect } from "next/navigation"

interface KnowledgeBaseIndexPageProps {
  params: Promise<{ id: string }>
}

export default async function KnowledgeBaseIndexPage({
  params,
}: KnowledgeBaseIndexPageProps) {
  const { id } = await params
  redirect(`/knowledge-bases/${id}/facts`)
}
