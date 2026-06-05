const CITATION_PATTERNS: RegExp[] = [
  /\(\s*sources?\s*(?:[#:]|no\.?|number)?\s*\d+(?:\s*[-–,]\s*\d+)*\s*\)/gi,
  /\[\s*sources?\s*(?:[#:]|no\.?|number)?\s*\d+(?:\s*[-–,]\s*\d+)*\s*\]/gi,
  /\(\s*#\s*\d+(?:\s*[-–,]\s*\d+)*\s*\)/gi,
  /\[\s*#\s*\d+(?:\s*[-–,]\s*\d+)*\s*\]/gi,
  /\bsources?\s*#\s*\d+\b/gi,
  /\bsources?\s+\d+\b/gi,
  /<\/?(?:SOURCE|CONTEXT)_BLOCK>/gi,
];

export function sanitizeChatAnswer(answer: string): string {
  let cleaned = answer ?? "";
  for (const pattern of CITATION_PATTERNS) {
    cleaned = cleaned.replace(pattern, "");
  }
  cleaned = cleaned.replace(/[ \t]+([,.;:!?])/g, "$1");
  cleaned = cleaned.replace(/[ \t]{2,}/g, " ");
  cleaned = cleaned.replace(/\n{3,}/g, "\n\n");
  cleaned = cleaned.replace(/\(\s*\)/g, "");
  cleaned = cleaned.replace(/\[\s*\]/g, "");
  return cleaned.trim();
}
