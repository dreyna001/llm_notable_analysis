type CaseArchiveNoticeBannerProps = {
  notices: string[];
  title?: string;
};

export function CaseArchiveNoticeBanner({
  notices,
  title = "Case notice",
}: CaseArchiveNoticeBannerProps) {
  if (!notices.length) {
    return null;
  }

  return (
    <div
      className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-950 dark:text-amber-50"
      role="status"
    >
      <div className="font-medium">{title}</div>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {notices.map((notice) => (
          <li key={notice}>{notice}</li>
        ))}
      </ul>
    </div>
  );
}
