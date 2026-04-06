import { redirect } from "next/navigation"

export default function KnowledgeBaseReviewPage() {
  redirect("/approval-queue?asset_type=training_entry")
}
