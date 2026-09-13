import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { SafeIcon } from "@/components/ui/safe-icon";

type EmptyStateProps = {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: {
    label: string;
    href?: string;
    onClick?: () => void;
  };
};

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: EmptyStateProps) {
  return (
    <div className="flex min-h-44 flex-col items-center justify-center gap-3 rounded-md border border-dashed bg-muted/25 p-6 text-center">
      <div className="flex size-10 items-center justify-center rounded-md border bg-background text-muted-foreground">
        <SafeIcon icon={Icon} />
      </div>
      <div className="flex max-w-md flex-col gap-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-sm leading-6 text-muted-foreground">{description}</p>
      </div>
      {action ? (
        <Button
          asChild={Boolean(action.href)}
          variant="outline"
          size="sm"
          onClick={action.onClick}
        >
          {action.href ? (
            <a href={action.href}>{action.label}</a>
          ) : (
            action.label
          )}
        </Button>
      ) : null}
    </div>
  );
}
