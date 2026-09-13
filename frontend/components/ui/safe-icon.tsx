import type { ComponentPropsWithoutRef } from "react";
import type { LucideIcon } from "lucide-react";

type SafeIconProps = ComponentPropsWithoutRef<LucideIcon> & {
  icon: LucideIcon;
};

export function SafeIcon({ icon: Icon, ...props }: SafeIconProps) {
  return (
    <Icon
      aria-hidden="true"
      data-darkreader-ignore
      data-icon="inline-start"
      suppressHydrationWarning
      {...props}
    />
  );
}
