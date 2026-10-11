import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Keep symbols, prices, and account ids left-to-right inside Arabic layout. */
export function LtrText({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <bdi dir="ltr" className={cn("unicode-bidi-isolate", className)}>
      {children}
    </bdi>
  );
}
