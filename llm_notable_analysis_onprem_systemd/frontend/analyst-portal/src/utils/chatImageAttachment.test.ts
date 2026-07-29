import { describe, expect, it } from "vitest";
import {
  fileToChatImagePayload,
  formatChatImageFileSize,
  validateChatImageFile,
} from "./chatImageAttachment";

describe("validateChatImageFile", () => {
  it("accepts supported image types", () => {
    const file = new File(["png"], "photo.png", { type: "image/png" });
    expect(validateChatImageFile(file)).toBeNull();
  });

  it("rejects unsupported mime types", () => {
    const file = new File(["pdf"], "doc.pdf", { type: "application/pdf" });
    expect(validateChatImageFile(file)).toMatch(/Only PNG, JPEG, WebP, and GIF/);
  });

  it("rejects files larger than the configured limit", () => {
    const file = new File([new Uint8Array(2048)], "large.png", {
      type: "image/png",
    });
    expect(validateChatImageFile(file, { maxBytes: 1024 })).toMatch(
      /1\.0 KB or smaller/,
    );
  });
});

describe("formatChatImageFileSize", () => {
  it("formats bytes, kilobytes, and megabytes", () => {
    expect(formatChatImageFileSize(512)).toBe("512 B");
    expect(formatChatImageFileSize(2048)).toBe("2.0 KB");
    expect(formatChatImageFileSize(2 * 1024 * 1024)).toBe("2.0 MB");
  });
});

describe("fileToChatImagePayload", () => {
  it("returns base64 payload without the data url prefix", async () => {
    const file = new File(["hello"], "hello.png", { type: "image/png" });
    const payload = await fileToChatImagePayload(file);
    expect(payload.media_type).toBe("image/png");
    expect(payload.data_base64).toBeTruthy();
    expect(payload.data_base64).not.toContain("data:");
  });
});
