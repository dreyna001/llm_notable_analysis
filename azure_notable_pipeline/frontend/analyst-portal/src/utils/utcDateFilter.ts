const UTC_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Normalize a date input value to YYYY-MM-DD when valid. */
export function normalizeUtcFilterDate(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  const dateOnly = trimmed.split("T")[0] ?? "";
  return UTC_DATE_RE.test(dateOnly) ? dateOnly : "";
}

function utcDayStartIso(date: string): string {
  return `${date}T00:00:00.000Z`;
}

function utcDayEndIso(date: string): string {
  return `${date}T23:59:59.999Z`;
}

/** Match processed_at against inclusive UTC calendar-day bounds. */
export function processedAtMatchesUtcDateRange(
  processedAt: string | null | undefined,
  startDate: string,
  endDate: string,
): boolean {
  if (!startDate && !endDate) {
    return true;
  }
  if (!processedAt) {
    return false;
  }
  if (startDate && processedAt < utcDayStartIso(startDate)) {
    return false;
  }
  if (endDate && processedAt > utcDayEndIso(endDate)) {
    return false;
  }
  return true;
}
