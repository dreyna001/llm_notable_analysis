import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PortalLoadFailure } from "./PortalLoadFailure";

describe("PortalLoadFailure", () => {
  it("shows the blocking load error message", () => {
    render(<PortalLoadFailure message="503: Portal API unavailable." />);

    expect(screen.getByText("Portal chat unavailable")).toBeInTheDocument();
    expect(screen.getByText("503: Portal API unavailable.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Reload the page or contact your operator if this persists.",
      ),
    ).toBeInTheDocument();
  });
});
