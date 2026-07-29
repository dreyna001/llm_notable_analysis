import type { ChatImageMediaType, ChatImagePayload } from "../types";

export const CHAT_IMAGE_MEDIA_TYPES: readonly ChatImageMediaType[] = [
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
];

export const CHAT_IMAGE_ACCEPT_ATTR = CHAT_IMAGE_MEDIA_TYPES.join(",");

export function isChatImageMediaType(value: string): value is ChatImageMediaType {
  return (CHAT_IMAGE_MEDIA_TYPES as readonly string[]).includes(value);
}

export function formatChatImageFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(bytes < 10_240 ? 1 : 0)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function validateChatImageFile(
  file: File,
  options?: { maxBytes?: number },
): string | null {
  if (!isChatImageMediaType(file.type)) {
    return "Only PNG, JPEG, WebP, and GIF images are supported.";
  }
  if (options?.maxBytes != null && file.size > options.maxBytes) {
    return `Image must be ${formatChatImageFileSize(options.maxBytes)} or smaller.`;
  }
  return null;
}

export function fileToChatImagePayload(file: File): Promise<ChatImagePayload> {
  return new Promise((resolve, reject) => {
    const mediaType = file.type;
    if (!isChatImageMediaType(mediaType)) {
      reject(new Error("Unsupported media type"));
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("Unexpected read result"));
        return;
      }
      const commaIndex = result.indexOf(",");
      const dataBase64 =
        commaIndex >= 0 ? result.slice(commaIndex + 1) : result;
      resolve({
        media_type: mediaType,
        data_base64: dataBase64,
      });
    };
    reader.onerror = () => {
      reject(new Error("File read failed"));
    };
    reader.readAsDataURL(file);
  });
}
