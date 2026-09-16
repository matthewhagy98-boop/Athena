import { render } from "@testing-library/react";
import { SPARKLINE_HEIGHT_CLASS, VelocitySparkline } from "./VelocitySparkline";

test.each([0, 1, 2])("renders nothing below three points (n=%i)", (n) => {
  const points = Array.from({ length: n }, (_, i) => i);
  const { container } = render(<VelocitySparkline points={points} />);

  expect(container.firstChild).toBeNull();
});

test("renders a wrapper at exactly three points", () => {
  const { container } = render(<VelocitySparkline points={[1, 2, 3]} />);

  // jsdom gives the ResponsiveContainer zero dimensions, so recharts may not
  // draw the chart internals -- assert on the wrapper element itself, which is
  // the boundary this guard actually controls.
  expect(container.firstChild).not.toBeNull();
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
});
