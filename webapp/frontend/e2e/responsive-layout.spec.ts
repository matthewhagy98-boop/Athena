import { expect, test, type Page } from "@playwright/test";

// A page that scrolls sideways on a phone is broken in a way no jsdom test can
// see: the viewport is the only thing that reveals it. The search page used to
// overflow to 576px of scroll width inside a 375px viewport, which squeezed the
// result cards' `min-w-0` column to literally zero and clipped every card.

/** Pages reachable from the nav, all sharing the shell's horizontal padding. */
const ROUTES = [
  { name: "search", path: "/#/search?q=cognitive", ready: "Established evidence" },
  { name: "saved searches", path: "/#/saved-searches", ready: "Saved searches" },
];

// 375 = iPhone SE/13 mini class; 414 = a large phone; 767 = the last pixel below
// the `md` breakpoint, where the stacked layout must still hold.
const WIDTHS = [375, 414, 767];

/**
 * Blocks the webfonts so the fallback face is used for good. The icon font is the
 * point: Material Symbols renders its ligature NAME ("bookmark_add") as literal
 * text until the font loads, which is far wider than the glyph. Waiting on a timer
 * would make this a race; blocking the font pins the worst case -- a slow or failed
 * font load -- so the layout has to hold without it.
 */
async function blockWebfonts(page: Page): Promise<void> {
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (route) => route.abort());
}

async function overflow(page: Page, path: string, ready: string) {
  await page.goto(path);
  await page.reload();
  await expect(page.getByText(ready).first()).toBeVisible();
  // Settle: this must be the steady state, not a frame mid-load.
  await page.waitForTimeout(600);
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
}

for (const route of ROUTES) {
  for (const width of WIDTHS) {
    test(`${route.name} does not scroll sideways at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.route("**/papers/velocity**", (r) => r.fulfill({ json: { velocities: {} } }));
      await blockWebfonts(page);

      const { scrollWidth, clientWidth } = await overflow(page, route.path, route.ready);

      expect(clientWidth).toBe(width);
      // 1px of tolerance for subpixel rounding; anything more is real overflow.
      expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1);
    });
  }
}

/** Loads the search page at `width` and reports the shell's layout metrics. */
async function shellMetrics(page: Page, width: number) {
  await page.setViewportSize({ width, height: 900 });
  await page.route("**/papers/velocity**", (r) => r.fulfill({ json: { velocities: {} } }));
  await blockWebfonts(page);
  await page.goto("/#/search?q=cognitive");
  await page.reload();
  await expect(page.getByText("Established evidence")).toBeVisible();
  await page.waitForTimeout(400);

  return page.evaluate(() => {
    const main = document.querySelector("main")!;
    const aside = document.querySelector("aside")!;
    const column = document.querySelector("div.mb-2.flex.gap-3.rounded-lg div.min-w-0");
    return {
      mainPaddingLeft: getComputedStyle(main).paddingLeft,
      asideWidth: Math.round(aside.getBoundingClientRect().width),
      asideBorderRight: getComputedStyle(aside).borderRightWidth,
      asideBorderBottom: getComputedStyle(aside).borderBottomWidth,
      contentWidth: Math.round(main.getBoundingClientRect().width),
      columnWidth: column ? Math.round(column.getBoundingClientRect().width) : null,
    };
  });
}

test("a phone spends its width on content, not padding", async ({ page }) => {
  // px-12 is 96px -- a quarter of a 375px screen -- which left the card's text
  // column around 219px. Not an overflow, but not a usable reading column either.
  const m = await shellMetrics(page, 375);

  expect(m.mainPaddingLeft).toBe("16px");
  expect(m.columnWidth).toBeGreaterThan(250);
});

test("the filter panel spans the width once it is stacked", async ({ page }) => {
  // Stacked above the results, a 208px-wide panel would sit in a full-width slot
  // with a vertical divider running down its right edge against nothing.
  const m = await shellMetrics(page, 375);

  expect(m.asideWidth).toBeGreaterThan(300);
  expect(m.asideWidth).toBeLessThanOrEqual(m.contentWidth);
  expect(m.asideBorderBottom).toBe("1px");
  expect(m.asideBorderRight).toBe("0px");
});

test("the desktop layout is unchanged", async ({ page }) => {
  // The whole fix is behind `md`, so the design above it must be exactly as before:
  // roomy padding, a 208px (w-52) sidebar, and its divider on the right.
  const m = await shellMetrics(page, 1280);

  expect(m.mainPaddingLeft).toBe("48px");
  expect(m.asideWidth).toBe(208);
  expect(m.asideBorderRight).toBe("1px");
  expect(m.asideBorderBottom).toBe("0px");
});

test("the result card keeps a usable column at 375px", async ({ page }) => {
  // The overflow's visible symptom: the card's text column collapsed to 0px wide,
  // so asserting "no scrollbar" alone is not enough -- the column has to be real.
  await page.setViewportSize({ width: 375, height: 900 });
  await page.route("**/papers/velocity**", (r) => r.fulfill({ json: { velocities: {} } }));
  await blockWebfonts(page);
  await page.goto("/#/search?q=cognitive");
  await page.reload();
  await expect(page.getByText("Established evidence")).toBeVisible();

  const column = page.locator("div.mb-2.flex.gap-3.rounded-lg div.min-w-0").first();
  const box = await column.boundingBox();

  expect(box).not.toBeNull();
  // The card sits inside the shell's padding and its own; a real column is most of
  // what is left, not a sliver.
  expect(box!.width).toBeGreaterThan(200);
});
