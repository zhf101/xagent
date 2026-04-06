import { KnowledgeBaseTrainingNewView } from "@/components/gdp/vanna/knowledge-base-training-new-view"

interface KnowledgeBaseQuestionSqlEditPageProps {
  params: Promise<{ entryId: string }>
}

export default async function KnowledgeBaseQuestionSqlEditPage({
  params,
}: KnowledgeBaseQuestionSqlEditPageProps) {
  const { entryId } = await params
  return <KnowledgeBaseTrainingNewView type="question_sql" entryId={Number(entryId)} />
}
