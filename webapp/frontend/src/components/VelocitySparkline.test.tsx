import { render } from "@testing-library/react";
import { SPARKLINE_HEIGHT_CLASS, VelocitySparkline } from "./VelocitySparkline";

/** Renders the series and reads the drawn geometry back as coordinate pairs. */
function coords(values: number[]): Array<[number, number]> {
  const { container } = render(<VelocitySparkline points={values} />);
  const points = container.querySelector("polyline")!.getAttribute("points")!;
  return points.split(" ").map((pair) => {
    const [x, y] = pair.split(",").map(Number);
    return [x, y];
  });
}

test.each([0, 1, 2])("renders nothing below three points (n=%i)", (n) => {
  const points = Array.from({ length: n }, (_, i) => i);
  const { container } = render(<VelocitySparkline points={points} />);

  expect(container.firstChild).toBeNull();
});

test("renders a wrapper at exactly three points", () => {
  const { container } = render(<VelocitySparkline points={[1, 2, 3]} />);

  expect(container.firstChild).not.toBeNull();
});

test("stays a two-node decoration", () => {
  // This renders on every search-result row, so a full 50-row page multiplies
  // whatever it costs by 50. The Recharts ResponsiveContainer it replaced expanded
  // to 25 nodes each -- measured at 1250 nodes, 54% of the whole page's elements,
  // plus a ResizeObserver per row re-measuring on every window resize. If a future
  // change reaches for a chart library again, this count is what notices.
  const { container } = render(<VelocitySparkline points={[1, 2, 3, 4, 5, 6]} />);
  const wrapper = container.firstElementChild!;

  expect(wrapper.querySelectorAll("*")).toHaveLength(2); // the svg and its polyline
});

test("draws an actual line, not just a wrapper", () => {
  // The inline SVG needs no layout engine, so unlike the ResponsiveContainer it
  // replaced, the drawn geometry is visible to jsdom and can be asserted.
  const { container } = render(<VelocitySparkline points={[1, 2, 3]} />);
  const polyline = container.querySelector("polyline");

  expect(polyline).not.toBeNull();
  expect(polyline!.getAttribute("points")!.split(" ")).toHaveLength(3);
});

test("keeps the established visual treatment", () => {
  const { container } = render(<VelocitySparkline points={[1, 2, 3]} />);
  const polyline = container.querySelector("polyline")!;

  expect(polyline).toHaveAttribute("stroke", "#006a61");
  expect(polyline).toHaveAttribute("stroke-width", "1.5");
  // No dots: a filled polyline would blot out the 64x16 box, and the previous
  // implementation drew the line only.
  expect(polyline).toHaveAttribute("fill", "none");
  expect(container.querySelector("circle")).toBeNull();
});

test("spans the full drawing box, oldest point left and newest right", () => {
  const pairs = coords([1, 2, 3, 4, 5]);

  expect(pairs[0][0]).toBe(1);
  expect(pairs[pairs.length - 1][0]).toBe(63);
  // Strictly increasing x: the series is plotted in order, never reversed.
  for (let i = 1; i < pairs.length; i++) {
    expect(pairs[i][0]).toBeGreaterThan(pairs[i - 1][0]);
  }
});

test("puts the lowest value at the bottom and the highest at the top", () => {
  // SVG y grows downward, so the maximum must have the SMALLEST y. Getting this
  // backwards would draw every trend upside down -- a rising citation count
  // shown as a decline -- while still producing a plausible-looking line.
  const pairs = coords([5, 1, 9]);
  const ys = pairs.map(([, y]) => y);

  expect(ys[2]).toBeLessThan(ys[0]); // 9 is the max -> highest on screen
  expect(ys[1]).toBeGreaterThan(ys[0]); // 1 is the min -> lowest on screen
  expect(Math.min(...ys)).toBe(1); // max sits at the top pad
  expect(Math.max(...ys)).toBe(15); // min sits at the bottom pad
});

test("draws a flat series down the middle instead of dividing by zero", () => {
  const pairs = coords([7, 7, 7]);

  for (const [, y] of pairs) expect(y).toBe(8);
});

test("stays inside the 64x16 box for any series", () => {
  // Anything outside would be clipped by the wrapper or overlap the badge text.
  const series = [
    [1, 2, 3],
    [0, 0, 0],
    [100, 1, 50, 3, 99],
    Array.from({ length: 12 }, (_, i) => i * 7),
  ];

  for (const values of series) {
    for (const [x, y] of coords(values)) {
      expect(x).toBeGreaterThanOrEqual(1);
      expect(x).toBeLessThanOrEqual(63);
      expect(y).toBeGreaterThanOrEqual(1);
      expect(y).toBeLessThanOrEqual(15);
    }
  }
});

test("the rendered wrapper is aria-hidden, since the badge text carries the accessible content", () => {
  const { container } = render(<VelocitySparkline points={[1, 2, 3]} />);

  expect(container.firstChild).toHaveAttribute("aria-hidden", "true");
});

test("the sparkline fits inside the badge's reserved height", () => {
  // jsdom does no layout, so this cannot be measured -- it is asserted structurally.
  // The badge reserves min-h-5 (20px); a 20px inline-block on align-middle stretched the
  // line box to ~24px and shifted every search-result row the moment a velocity arrived.
  // h-4 (16px) matches the text's line box, and align-text-bottom keeps it on the
  // baseline rather than recentring it.
  const { container } = render(<VelocitySparkline points={[1, 2, 3]} />);
  const wrapper = container.querySelector('[aria-hidden="true"]');

  expect(SPARKLINE_HEIGHT_CLASS).toBe("h-4");
  expect(wrapper).toHaveClass(SPARKLINE_HEIGHT_CLASS);
  expect(wrapper).toHaveClass("align-text-bottom");
  expect(wrapper).not.toHaveClass("h-5");
  expect(wrapper).not.toHaveClass("align-middle");
  // Width is part of the same constraint: this sits inline between the figure and the
  // percentile clause, so widening it pushes that clause toward a second line on a narrow
  // card -- the same shift by a different route.
  expect(wrapper).toHaveClass("w-16");
});
