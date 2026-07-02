import { cn } from "@/lib/utils";

type ProgressProps = {
  value: number;
  variant?: "default" | "success";
  className?: string;
};

export function Progress({
  value,
  variant = "default",
  className,
}: ProgressProps) {
  const boundedValue = Math.max(0, Math.min(100, value));
  return (
    <div
      className={cn(
        "h-2 w-full overflow-hidden rounded-md bg-muted",
        variant === "success" && "bg-emerald-500/15",
        className,
      )}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={boundedValue}
    >
      <div
        className={cn(
          "h-full rounded-md bg-primary transition-all duration-500",
          variant === "success" && "bg-emerald-500",
        )}
        style={{ width: `${boundedValue}%` }}
      />
    </div>
  );
}
