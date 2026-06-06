import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function DetailMuted({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

export function DetailError({ children }: { children: ReactNode }) {
  return <p className="text-sm text-destructive">{children}</p>;
}

export function DetailSectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </p>
  );
}

export function DetailCard({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={className}>
      <CardContent className="p-4">{children}</CardContent>
    </Card>
  );
}

export function DetailCardTitle({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </h3>
  );
}

export function DetailMetricGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{children}</div>
  );
}

export function DetailMetric({
  label,
  value,
  sub,
  valueStyle,
}: {
  label: string;
  value: string;
  sub?: string;
  valueStyle?: React.CSSProperties;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <p className="mt-1 text-2xl font-semibold tracking-tight" style={valueStyle}>
          {value}
        </p>
        {sub ? (
          <p className="mt-1 text-xs text-muted-foreground">{sub}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function DetailTwoCol({ children }: { children: ReactNode }) {
  return <div className="grid gap-4 lg:grid-cols-2">{children}</div>;
}

export function DetailProgressRow({
  label,
  width,
  color,
  score,
}: {
  label: string;
  width: number;
  color: string;
  score: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-20 shrink-0 text-xs text-muted-foreground">{label}</span>
      <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${width}%`, background: color }}
        />
      </div>
      <span className="w-12 shrink-0 text-right text-sm font-medium" style={{ color }}>
        {score}
      </span>
    </div>
  );
}

export function DetailHypothesisBlock({
  title,
  body,
  variant,
}: {
  title: string;
  body: string;
  variant: "benign" | "adversary";
}) {
  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        variant === "benign"
          ? "border-emerald-500/30 bg-emerald-500/5"
          : "border-destructive/30 bg-destructive/5",
      )}
    >
      <p
        className={cn(
          "font-medium",
          variant === "benign" ? "text-emerald-400" : "text-destructive",
        )}
      >
        {title}
      </p>
      <p className="mt-2 text-sm text-muted-foreground">{body}</p>
    </div>
  );
}

export function DetailDriverGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-4 md:grid-cols-2">{children}</div>;
}

export function DetailDriverCol({
  title,
  variant,
  children,
}: {
  title: string;
  variant: "malicious" | "benign";
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        variant === "malicious"
          ? "border-destructive/20 bg-destructive/5"
          : "border-emerald-500/20 bg-emerald-500/5",
      )}
    >
      <h4
        className={cn(
          "mb-2 text-sm font-semibold",
          variant === "malicious" ? "text-destructive" : "text-emerald-400",
        )}
      >
        {title}
      </h4>
      {children}
    </div>
  );
}

export function DetailBulletList({ items }: { items: string[] }) {
  return (
    <ul className="space-y-2 text-sm text-foreground/90">
      {items.map((item) => (
        <li className="border-b border-border/40 pb-2 last:border-0 last:pb-0" key={item}>
          {item}
        </li>
      ))}
    </ul>
  );
}

export function hypothesisChipClass(type: string): string {
  return cn(
    "inline-flex shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
    type === "benign" && "bg-emerald-500/15 text-emerald-400",
    type === "adversary" && "bg-destructive/15 text-destructive",
    type === "ttp" && "bg-primary/15 text-primary",
    type === "unknown" && "bg-muted text-muted-foreground",
  );
}

export function hypothesisTitleClass(type: string): string {
  return cn(
    "min-w-0 flex-1 text-left text-sm font-medium",
    type === "benign" && "text-emerald-400",
    type === "adversary" && "text-destructive",
    type === "ttp" && "text-primary",
    type === "unknown" && "text-muted-foreground",
  );
}

export function ttpScoreBadgeVariant(
  label: string,
): "destructive" | "warning" | "muted" {
  switch (label.toLowerCase()) {
    case "high":
      return "destructive";
    case "medium":
      return "warning";
    default:
      return "muted";
  }
}

export function miniTitleClass(titleClass: string): string {
  const base = "mt-4 first:mt-0 text-xs font-semibold uppercase tracking-wide";
  if (titleClass.includes("immediate")) {
    return cn(base, "text-destructive");
  }
  if (titleClass.includes("short")) {
    return cn(base, "text-amber-400");
  }
  if (titleClass.includes("long") || titleClass.includes("support")) {
    return cn(base, "text-emerald-400");
  }
  if (titleClass.includes("gap") || titleClass.includes("uncertainty")) {
    return cn(base, "text-amber-400");
  }
  if (titleClass.includes("pivot")) {
    return cn(base, "text-primary");
  }
  return cn(base, "text-muted-foreground");
}

export function DetailMiniTitle({
  children,
  titleClass = "",
}: {
  children: ReactNode;
  titleClass?: string;
}) {
  return <p className={miniTitleClass(titleClass)}>{children}</p>;
}

export function DetailPivotBlock({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-sm text-foreground/90">
      {children}
    </div>
  );
}

export function DetailKvGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-2">{children}</div>;
}

export function DetailKvRow({
  label,
  value,
  danger = false,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <div className="grid gap-1 border-b border-border/40 py-2 text-sm last:border-0 sm:grid-cols-[minmax(8rem,12rem)_1fr] sm:gap-4">
      <span className="font-medium text-muted-foreground">{label}</span>
      <span className={cn("break-all", danger && "text-destructive")}>{value}</span>
    </div>
  );
}

export function DetailMetaGrid({ children }: { children: ReactNode }) {
  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-[minmax(8rem,10rem)_1fr]">
      {children}
    </dl>
  );
}

export function DetailMetaTerm({ children }: { children: ReactNode }) {
  return <dt className="font-medium text-muted-foreground">{children}</dt>;
}

export function DetailMetaValue({ children }: { children: ReactNode }) {
  return <dd className="break-all">{children}</dd>;
}

export function DetailCodeBlock({ children }: { children: ReactNode }) {
  return (
    <pre className="max-h-[32rem] overflow-auto rounded-lg border border-border bg-muted/40 p-4 text-xs leading-relaxed text-foreground/90">
      {children}
    </pre>
  );
}

export function DetailStack({ children }: { children: ReactNode }) {
  return <div className="space-y-3">{children}</div>;
}

export function CollapsibleDetailCard({
  open,
  onToggle,
  chip,
  title,
  titleClassName,
  trailing,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  chip: ReactNode;
  title: string;
  titleClassName?: string;
  trailing?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card>
      <button
        className="flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-muted/40"
        type="button"
        onClick={onToggle}
      >
        {chip}
        <span className={cn("min-w-0 flex-1 text-sm font-medium", titleClassName)}>
          {title}
        </span>
        {trailing}
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open ? (
        <CardContent className="space-y-3 border-t border-border/60 pt-4">
          {children}
        </CardContent>
      ) : null}
    </Card>
  );
}

export function InterpretationAssessmentBadge({
  assessment,
}: {
  assessment: unknown;
}) {
  const value = String(assessment ?? "unknown").toLowerCase();
  const variant =
    value === "supports"
      ? "success"
      : value === "weakens"
        ? "destructive"
        : value === "inconclusive"
          ? "warning"
          : "muted";
  const label = value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return <Badge variant={variant}>{label}</Badge>;
}

export function InterpretationDeltaBadge({ delta }: { delta: unknown }) {
  const value = String(delta ?? "unknown").toLowerCase();
  const variant =
    value === "increase"
      ? "destructive"
      : value === "decrease"
        ? "success"
        : value === "unchanged"
          ? "muted"
          : "warning";
  const label = value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return <Badge variant={variant}>{label}</Badge>;
}

export function DetailHeroMeta({
  items,
}: {
  items: Array<{ label: string; value: string }>;
}) {
  return (
    <dl className="grid gap-4 sm:grid-cols-3">
      {items.map((item) => (
        <div key={item.label}>
          <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {item.label}
          </dt>
          <dd className="mt-1 text-sm font-medium">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function DetailHero({
  caseId,
  chatLink,
  meta,
}: {
  caseId: string;
  chatLink: ReactNode;
  meta: Array<{ label: string; value: string }>;
}) {
  return (
    <Card>
      <CardHeader className="space-y-4">
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Case reconciliation
          </p>
          <CardTitle className="text-2xl">{caseId}</CardTitle>
          <p className="text-sm text-muted-foreground">
            Review the alert, Agent verdict, and source evidence.
          </p>
          <div>{chatLink}</div>
        </div>
        <DetailHeroMeta items={meta} />
      </CardHeader>
    </Card>
  );
}
