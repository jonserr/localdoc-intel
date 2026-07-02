import { FileText, Hash } from "lucide-react";
import React from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SafeIcon } from "@/components/ui/safe-icon";

type CitationCardProps = {
  document: string;
  range: string;
  score: string;
  text: string;
  sourceNumber?: number;
  retrievalSource?: string;
  chunkId?: number;
  documentId?: number;
};

export function CitationCard({
  document,
  range,
  score,
  text,
  sourceNumber,
  retrievalSource,
  chunkId,
  documentId,
}: CitationCardProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex min-w-0 items-start justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-2">
            <CardTitle className="flex min-w-0 items-center gap-2 text-sm">
              <SafeIcon icon={FileText} className="shrink-0" />
              {sourceNumber ? (
                <span className="shrink-0 text-primary">[{sourceNumber}]</span>
              ) : null}
              <span className="min-w-0 truncate">{document}</span>
            </CardTitle>
            <div className="flex flex-wrap gap-2">
              {retrievalSource ? (
                <Badge variant="outline">{retrievalSource}</Badge>
              ) : null}
              {documentId ? (
                <Badge variant="muted">
                  <SafeIcon icon={Hash} />
                  doc {documentId}
                </Badge>
              ) : null}
              {chunkId ? (
                <Badge variant="muted">
                  <SafeIcon icon={Hash} />
                  chunk {chunkId}
                </Badge>
              ) : null}
            </div>
          </div>
          <Badge variant="secondary" className="shrink-0">
            score {score}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <span className="text-xs font-medium text-muted-foreground">
          {range}
        </span>
        <p className="break-words leading-6 text-muted-foreground">{text}</p>
      </CardContent>
    </Card>
  );
}
