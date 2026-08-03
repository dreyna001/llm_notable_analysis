import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  CasesTableSkeleton,
  ChatConversationSkeleton,
} from "./LoadingSkeletons";

describe("LoadingSkeletons", () => {
  it("renders accessible loading regions for cases and chat", () => {
    const { rerender } = render(<CasesTableSkeleton rows={2} />);
    expect(screen.getByLabelText("Loading cases")).toBeInTheDocument();

    rerender(<ChatConversationSkeleton />);
    expect(screen.getByLabelText("Loading conversation")).toBeInTheDocument();
  });
});
