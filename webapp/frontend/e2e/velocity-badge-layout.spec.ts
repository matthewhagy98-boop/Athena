import { expect, test, type Page } from "@playwright/test";
import type { PaperVelocity } from "../src/api/types";

// The plan for this work forbids layout shift on the search page: the badge
// region's height is reserved from first paint, so a velocity arriving cannot
// move the card (docs/superpowers/plans/2026-09-08-citation-velocity-ui.md, §"No
// layout shift").
//
// jsdom does no layout, so the vitest suite can only assert class names -- it
// cannot see that the badge's text wraps to a second line and grows the row.
// This runs in a real browser and measures the region instead.

/** The reserved single-line height of the badge region (Tailwind min-h-5). */
const RESERVED_HEIGHT = 20;

// The longest text the badge can produce, on the rows most likely to produce it:
// a ready velocity carries the figure, a percentile clause AND an age suffix, and
// a 12-point series draws the sparkline alongside them.
const WORST_CASE: PaperVelocity = {
  status: "ready",
  velocity_per_30d: 42,
  window_start_observed_at: "2026-08-01T00:00:00Z",
  window_end_observed_at: "2026-09-01T00:00:00Z",
  observation_count: 12,
  first_observed_at: "2026-01-01T00:00:00Z",
  percentile: 88,
  cohort_size: 1240,
  is_retracted: false,
  // Comfortably past AGING_DAYS, so the " · as of N days ago" suffix renders.
  computed_at: new Date(Date.now() - 9 * 86400000).toISOString(),
  recent_counts: [3, 5, 4, 7, 9, 8, 12, 11, 15, 14, 18, 21],
};

let serveVelocity = false;

async function installVelocityStub(page: Page): Promise<void> {
  await page.route("**/papers/velocity**", async (route) => {
    const ids = new URL(route.request().url()).searchParams.getAll("paper_ids");
    const velocities: Record<string, PaperVelocity> = {};
    if (serveVelocity) for (const id of ids) velocities[id] = WORST_CASE;
    await route.fulfill({ json: { velocities } });
  });
}

async function measureBadgeRegions(page: Page, withVelocity: boolean): Promise<number[]> {
  serveVelocity = withVelocity;
  await page.goto("/#/search?q=cognitive");
  // Hash-only navigation is same-document: without a reload React Query keeps the
  // response cached from the previous pass and the second measurement is a no-op.
  await page.reload();
  await expect(page.getByText("Established evidence")).toBeVisible();

  const regions = page.locator("[data-testid='citation-velocity-region']");
  await expect(regions.first()).toBeVisible();
  if (withVelocity) {
    await expect(regions.first()).toContainText("citations in the last 30 days");
  }
  return regions.evaluateAll((nodes) => nodes.map((n) => n.getBoundingClientRect().height));
}

// 900px is where the badge first wrapped before the fix -- well above any mobile
// breakpoint, on an ordinary laptop-with-a-sidebar width. 375px is iPhone-class.
for (const width of [1280, 900, 768, 375]) {
  test(`badge region reserves its height at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installVelocityStub(page);

    const before = await measureBadgeRegions(page, false);
    const after = await measureBadgeRegions(page, true);

    expect(before.length).toBeGreaterThan(0);
    expect(after).toHaveLength(before.length);

    // The region is one line tall whether or not a velocity ever arrives, so the
    // rows below it never move.
    expect(before).toEqual(before.map(() => RESERVED_HEIGHT));
    expect(after).toEqual(after.map(() => RESERVED_HEIGHT));
  });
}
