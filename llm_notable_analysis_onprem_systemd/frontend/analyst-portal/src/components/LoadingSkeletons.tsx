import type { ReactNode } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type LoadingRegionProps = {
  label: string;
  className?: string;
};

function LoadingRegion({
  label,
  className,
  children,
}: LoadingRegionProps & {
  children: ReactNode;
}) {
  return (
    <div aria-busy="true" aria-label={label} className={className}>
      {children}
    </div>
  );
}

export function CasesTableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <LoadingRegion className="overflow-x-auto" label="Loading cases">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="pb-3 pr-4 font-medium">Case ID</th>
            <th className="pb-3 pr-4 font-medium">Processed</th>
            <th className="pb-3 pr-4 font-medium">Verdict</th>
            <th className="pb-3 pr-4 font-medium">Alert name</th>
            <th className="pb-3 pr-4 font-medium">Chatbot Readiness</th>
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }, (_, index) => (
            <tr className="border-b border-border/60" key={`case-skeleton-${index}`}>
              <td className="py-3 pr-4">
                <Skeleton className="h-4 w-28" />
                <Skeleton className="mt-1.5 h-3 w-20" />
              </td>
              <td className="py-3 pr-4">
                <Skeleton className="h-4 w-32" />
              </td>
              <td className="py-3 pr-4">
                <Skeleton className="h-6 w-24 rounded-sm" />
              </td>
              <td className="py-3 pr-4">
                <Skeleton className="h-4 w-40" />
              </td>
              <td className="py-3 pr-4">
                <Skeleton className="h-6 w-20 rounded-sm" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </LoadingRegion>
  );
}

export function ChatConversationSkeleton() {
  return (
    <LoadingRegion
      className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-8"
      label="Loading conversation"
    >
      <div className="flex justify-end">
        <Skeleton className="h-10 w-[55%] rounded-md" />
      </div>
      <div className="space-y-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-[92%]" />
        <Skeleton className="h-4 w-[78%]" />
      </div>
      <div className="flex justify-end">
        <Skeleton className="h-10 w-[45%] rounded-md" />
      </div>
      <div className="space-y-2">
        <Skeleton className="h-4 w-[88%]" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-[64%]" />
      </div>
    </LoadingRegion>
  );
}

export function CaseAttachListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <LoadingRegion className="space-y-2 px-1 py-1" label="Loading cases">
      {Array.from({ length: rows }, (_, index) => (
        <div className="rounded-md px-2 py-1.5" key={`attach-skeleton-${index}`}>
          <Skeleton className="h-4 w-[75%]" />
          <Skeleton className="mt-1.5 h-3 w-[50%]" />
        </div>
      ))}
    </LoadingRegion>
  );
}

export function CaseAttachMetaSkeleton() {
  return (
    <LoadingRegion className="space-y-1.5" label="Loading case details">
      <Skeleton className="h-3 w-20" />
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-3 w-28" />
    </LoadingRegion>
  );
}

export function CaseDetailMetricsSkeleton() {
  return (
    <LoadingRegion label="Loading case details">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }, (_, index) => (
          <div
            className="rounded-lg border bg-card p-4 shadow-sm"
            key={`metric-skeleton-${index}`}
          >
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-3 h-8 w-20" />
            <Skeleton className="mt-2 h-3 w-32" />
          </div>
        ))}
      </div>
      <div className="mt-6 flex gap-2">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton className="h-9 w-24 rounded-md" key={`tab-skeleton-${index}`} />
        ))}
      </div>
      <div className="mt-4 space-y-3 rounded-lg border bg-card p-4 shadow-sm">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-[90%]" />
        <Skeleton className="h-4 w-[75%]" />
      </div>
    </LoadingRegion>
  );
}

export function PortalWorkspaceSkeleton({ className }: { className?: string }) {
  return (
    <LoadingRegion
      className={cn(
        "flex min-h-0 flex-1 items-center justify-center px-6",
        className,
      )}
      label="Checking portal capabilities"
    >
      <div className="mx-auto w-full max-w-3xl space-y-6">
        <div className="space-y-2 text-center">
          <Skeleton className="mx-auto h-6 w-48" />
          <Skeleton className="mx-auto h-4 w-72" />
        </div>
        <Skeleton className="mx-auto h-24 w-full rounded-lg" />
      </div>
    </LoadingRegion>
  );
}
