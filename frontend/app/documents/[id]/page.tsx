import { DocumentDetailClient } from "@/components/documents/document-detail-client";

export default async function DocumentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <DocumentDetailClient id={id} />;
}
