import { render } from "@testing-library/react";
import { VelocitySparkline } from "./VelocitySparkline";

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
