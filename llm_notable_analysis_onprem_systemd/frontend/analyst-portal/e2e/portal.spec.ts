import { expect, test } from "@playwright/test";
import {
  alertName,
  completenessUiLabel,
  loadPortalFixture,
  reconciliationSummary,
  retrievalUiLabel,
  verdictUiLabel,
  type PortalFixture,
} from "./portal-api";
import { portalEnv } from "./portal-env";

const env = portalEnv();
let fixture: PortalFixture;

function caseRow(page: import("@playwright/test").Page) {
  return page.getByRole("row").filter({
    has: page.getByRole("link", {
      name: fixture.caseSummary.case_id,
      exact: true,
    }),
  });
}

async function gotoHomeWithCase(
  page: import("@playwright/test").Page,
  caseId: string,
) {
  await page.goto(`/?case_id=${encodeURIComponent(caseId)}`);
  await expect(page.getByText(/Checking portal capabilities/)).toBeHidden({
    timeout: 30_000,
  });
}

async function expectSelectedCaseAttached(
  page: import("@playwright/test").Page,
  caseId: string,
) {
  const modeSelect = page.getByRole("combobox", { name: "Mode" });
  if (await modeSelect.isVisible()) {
    await modeSelect.click();
    await page.getByRole("option", { name: "Selected case + knowledge base" }).click();
  }
  const sidebar = page.locator('aside[aria-label="Portal navigation and chats"]');
  await expect(sidebar.getByText("Case attached")).toBeVisible();
  await expect(sidebar.getByRole("link", { name: caseId })).toBeVisible();
}

test.beforeAll(async ({ request }) => {
  fixture = await loadPortalFixture(request, env.caseId);
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.clear();
  });
});

test.describe("Analyst portal E2E", () => {
  test("loads SPA shell and primary navigation", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: "Alert Analysis Portal" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
    await expect(page.getByRole("link", { name: /AI Case Assistant/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Cases/ })).toBeVisible();
    await expect(page.getByText("AI Case Assistant").first()).toBeVisible();

    await page.getByRole("link", { name: /Cases/ }).click();
    await expect(page).toHaveURL(/\/cases$/);
    await expect(page.getByRole("heading", { name: "Cases" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Case ID" })).toBeVisible();

    await page.getByRole("link", { name: /AI Case Assistant/ }).click();
    await expect(page).toHaveURL(/\/(\?.*)?$/);
  });

  test("lists the sample case with API-aligned summary data", async ({ page }) => {
    await page.goto("/cases");
    await expect(page.getByText("Loading cases...")).toBeHidden();

    const row = caseRow(page);
    await expect(row).toBeVisible();
    await expect(row.getByRole("link", { name: fixture.caseSummary.case_id })).toBeVisible();

    if (fixture.caseSummary.search_name) {
      await expect(row.getByText(fixture.caseSummary.search_name)).toBeVisible();
    }
    await expect(row.getByText(verdictUiLabel(fixture.caseSummary.verdict))).toBeVisible();
    await expect(
      row.getByText(retrievalUiLabel(fixture.caseSummary.retrieval_status)),
    ).toBeVisible();
    await expect(
      row.getByText(completenessUiLabel(fixture.caseSummary.source_completeness)),
    ).toBeVisible();
  });

  test("filters cases by alert name, verdict, and clear", async ({ page }) => {
    const searchTerm = fixture.caseSummary.search_name ?? fixture.caseSummary.case_id;
    const verdictFilter =
      fixture.caseSummary.verdict?.includes("benign") ||
      fixture.caseSummary.verdict?.includes("malicious")
        ? verdictUiLabel(fixture.caseSummary.verdict)
        : null;

    await page.goto("/cases");
    await expect(page.getByText("Loading cases...")).toBeHidden();

    await page.getByLabel("Alert name").fill(searchTerm.slice(0, Math.max(4, searchTerm.length - 2)));
    await page.waitForTimeout(350);
    await expect(caseRow(page)).toBeVisible();

    if (verdictFilter) {
      await page.getByRole("combobox", { name: "Verdict" }).click();
      await page.getByRole("option", { name: verdictFilter }).click();
      await page.getByRole("button", { name: "Apply filters" }).click();
      await expect(page.getByText("Loading cases...")).toBeHidden();
      await expect(caseRow(page)).toBeVisible();
    }

    await page.getByRole("button", { name: "Clear" }).click();
    await expect(page.getByLabel("Alert name")).toHaveValue("");
    await expect(caseRow(page)).toBeVisible();
  });

  test("shows case detail metrics and every available analysis tab", async ({ page }) => {
    const name = alertName(fixture.caseDetail);
    const summary = reconciliationSummary(fixture.caseDetail);

    await page.goto(`/cases/${encodeURIComponent(env.caseId)}`);
    await expect(page.getByText("Loading case...")).toBeHidden();

    await expect(
      page.getByText(env.caseId, { exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByText(name).first()).toBeVisible();
    await expect(page.getByText("Confidence", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Chatbot readiness", { exact: true }).first()).toBeVisible();
    await expect(
      page.getByText(retrievalUiLabel(fixture.caseDetail.metadata.retrieval_status)),
    ).toBeVisible();
    await expect(
      page.getByText(
        completenessUiLabel(fixture.caseDetail.metadata.source_completeness),
      ),
    ).toBeVisible();

    for (const label of fixture.expectedTabLabels) {
      await page.getByRole("tab", { name: label }).click();
      await expect(page.getByRole("tab", { name: label })).toHaveAttribute(
        "data-state",
        "active",
      );
    }

    if (summary) {
      await page.getByRole("tab", { name: "Verdict" }).click();
      await expect(page.getByText(summary)).toBeVisible();
    }

    await page.getByRole("tab", { name: "Case Metadata" }).click();
    await expect(page.getByRole("tab", { name: "Case Metadata" })).toHaveAttribute(
      "data-state",
      "active",
    );
    const metadataPanel = page.getByRole("tabpanel");
    await expect(metadataPanel.getByText("Case ID")).toBeVisible();
    await expect(metadataPanel.getByText(env.caseId, { exact: true })).toBeVisible();
    await expect(metadataPanel.getByText("Notable name")).toBeVisible();
  });

  test("links case detail to the home assistant with the case attached", async ({
    page,
  }) => {
    test.skip(!fixture.capabilities.case_qa_enabled, "case_qa_enabled is off");

    const name = alertName(fixture.caseDetail);

    await page.goto(`/cases/${encodeURIComponent(env.caseId)}`);
    await expect(page.getByText("Loading case...")).toBeHidden();

    const assistantLink = page.getByRole("link", {
      name: /Ask Assistant about this case/,
    });
    await expect(assistantLink).toHaveAttribute(
      "href",
      `/?case_id=${encodeURIComponent(env.caseId)}`,
    );

    await gotoHomeWithCase(page, env.caseId);
    await expect(page).toHaveURL(
      new RegExp(`case_id=${encodeURIComponent(env.caseId).replace(/-/g, "\\-")}`),
    );
    await expectSelectedCaseAttached(page, env.caseId);
    await expect(page.locator('aside[aria-label="Portal navigation and chats"]').getByText(name).first()).toBeVisible();
  });

  test("surfaces a missing case on detail and attach flows", async ({ page }) => {
    test.skip(!fixture.capabilities.case_qa_enabled, "case_qa_enabled is off");

    const missingId = "portal-e2e-missing-case";

    await page.goto(`/cases/${encodeURIComponent(missingId)}`);
    await expect(page.getByText(/404:|not found|Missing case/i)).toBeVisible();

    await page.goto(`/?case_id=${encodeURIComponent(missingId)}`);
    await expect(page.getByText(/Checking portal capabilities/)).toBeHidden({
      timeout: 30_000,
    });
    await expect(page.getByRole("status")).toContainText(
      "Case not found or unavailable.",
    );
  });

  test("chat assistant modes answer for the sample case", async ({ page }) => {
    test.skip(!env.runChat, "PORTAL_E2E_CHAT=false");
    test.skip(!fixture.capabilities.case_qa_enabled, "case_qa_enabled is off");

    // This test issues up to two LLM round-trips, each allowed up to
    // chatTimeoutMs. Give it a budget that covers both plus UI overhead so the
    // global default per-test timeout does not cut a slow turn short.
    test.setTimeout(env.chatTimeoutMs * 2 + 60_000);

    const question =
      "What is the verdict for this case? Answer in one sentence using only case evidence.";

    await gotoHomeWithCase(page, env.caseId);
    await expectSelectedCaseAttached(page, env.caseId);
    await expect(page.getByText("Loading case details...")).toBeHidden();

    const composer = page.getByPlaceholder(/Ask about/i);
    await expect(composer).toBeEnabled();
    await composer.fill(question);
    await page.getByRole("button", { name: "Send" }).click();

    await expect(page.getByText(question)).toBeVisible();
    await expect(page.getByRole("button", { name: "Stop response" })).toBeHidden({
      timeout: env.chatTimeoutMs,
    });
    const assistantReply = page
      .locator("div.flex.flex-col.gap-4")
      .filter({ hasText: question })
      .locator(".max-w-3xl")
      .last();
    await expect(assistantReply).not.toBeEmpty({ timeout: 5_000 });

    if (fixture.capabilities.global_retrieval_enabled) {
      await page.getByRole("combobox", { name: "Mode" }).click();
      await page.getByRole("option", { name: "All cases + knowledge base" }).click();

      const globalQuestion =
        "How many archived cases mention Portal E2E Test? Answer briefly from archived case context.";
      await composer.fill(globalQuestion);
      await page.getByRole("button", { name: "Send" }).click();
      await expect(page.getByText(globalQuestion)).toBeVisible();
      await expect(page.getByRole("button", { name: "Stop response" })).toBeHidden({
        timeout: env.chatTimeoutMs,
      });
    }
  });
});
