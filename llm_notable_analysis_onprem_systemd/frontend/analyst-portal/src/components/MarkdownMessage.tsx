import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

type MarkdownMessageProps = {
  text: string;
  className?: string;
};

function normalizeMarkdown(text: string): string {
  return text
    .replace(/\\n/g, "\n")
    .replace(/([^\n])(\s*)(#{1,6}\s+)/g, "$1\n\n$3")
    .replace(/([^\n])(\s*)(```[a-zA-Z0-9_-]*)/g, "$1\n\n$3")
    .replace(/(```[a-zA-Z0-9_-]*)[ \t]+/g, "$1\n")
    .replace(/[ \t]+```/g, "\n```")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const markdownComponents: Components = {
  a({ className, node: _node, ...props }) {
    return (
      <a
        className={cn("underline underline-offset-4", className)}
        rel="noreferrer"
        target="_blank"
        {...props}
      />
    );
  },
  blockquote({ className, node: _node, ...props }) {
    return (
      <blockquote
        className={cn(
          "border-l-2 border-border pl-4 text-muted-foreground",
          className,
        )}
        {...props}
      />
    );
  },
  code({ className, node: _node, ...props }) {
    return (
      <code
        className={cn(
          "rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]",
          className,
        )}
        {...props}
      />
    );
  },
  h1({ className, node: _node, ...props }) {
    return (
      <h1
        className={cn("mt-5 text-xl font-semibold tracking-tight", className)}
        {...props}
      />
    );
  },
  h2({ className, node: _node, ...props }) {
    return (
      <h2
        className={cn("mt-5 text-lg font-semibold tracking-tight", className)}
        {...props}
      />
    );
  },
  h3({ className, node: _node, ...props }) {
    return (
      <h3
        className={cn("mt-4 text-base font-semibold tracking-tight", className)}
        {...props}
      />
    );
  },
  li({ className, node: _node, ...props }) {
    return <li className={cn("pl-1", className)} {...props} />;
  },
  ol({ className, node: _node, ...props }) {
    return (
      <ol
        className={cn("my-3 list-decimal space-y-1 pl-6", className)}
        {...props}
      />
    );
  },
  p({ className, node: _node, ...props }) {
    return <p className={cn("my-3 first:mt-0 last:mb-0", className)} {...props} />;
  },
  pre({ className, node: _node, ...props }) {
    return (
      <pre
        className={cn(
          "chat-scrollbar my-3 overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs leading-relaxed",
          className,
        )}
        {...props}
      />
    );
  },
  table({ className, node: _node, ...props }) {
    return (
      <div className="chat-scrollbar my-3 overflow-x-auto">
        <table
          className={cn("w-full border-collapse text-sm", className)}
          {...props}
        />
      </div>
    );
  },
  td({ className, node: _node, ...props }) {
    return (
      <td
        className={cn("border border-border px-2 py-1 align-top", className)}
        {...props}
      />
    );
  },
  th({ className, node: _node, ...props }) {
    return (
      <th
        className={cn(
          "border border-border bg-muted px-2 py-1 text-left font-medium",
          className,
        )}
        {...props}
      />
    );
  },
  ul({ className, node: _node, ...props }) {
    return (
      <ul
        className={cn("my-3 list-disc space-y-1 pl-6", className)}
        {...props}
      />
    );
  },
};

export function MarkdownMessage({ text, className }: MarkdownMessageProps) {
  const normalizedText = normalizeMarkdown(text);

  return (
    <div className={cn("max-w-3xl text-sm leading-relaxed", className)}>
      <ReactMarkdown components={markdownComponents} remarkPlugins={[remarkGfm]}>
        {normalizedText}
      </ReactMarkdown>
    </div>
  );
}
