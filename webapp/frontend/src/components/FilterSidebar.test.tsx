import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SearchParams, TopicRef } from "../api/types";
import { FilterSidebar } from "./FilterSidebar";

const TOPICS: TopicRef[] = [{ id: "t1", canonical_label: "Demo topic" }];

function renderSidebar(
  value: SearchParams = {},
  onApply: (params: SearchParams) => void = () => {},
) {
  return render(<FilterSidebar topics={TOPICS} value={value} onApply={onApply} />);
}

/** The toggle, found by its role rather than a test id. */
function toggle() {
  return screen.getByRole("button", { name: /^filters/i });
}

// Note on what jsdom can and cannot check here: the panel is hidden with a Tailwind
// class, and no stylesheet is loaded in these tests, so the controls are always
// "visible" to Testing Library. Collapsing is therefore asserted through the state
// the assistive layer actually reads -- aria-expanded and aria-controls -- and the
// real hiding is measured in a browser by e2e/responsive-layout.spec.ts.

test("the panel starts collapsed", () => {
  renderSidebar();

  expect(toggle()).toHaveAttribute("aria-expanded", "false");
});

test("activating the toggle expands the panel", async () => {
  const user = userEvent.setup();
  renderSidebar();

  await user.click(toggle());

  expect(toggle()).toHaveAttribute("aria-expanded", "true");
});

test("activating the toggle again collapses it", async () => {
  const user = userEvent.setup();
  renderSidebar();

  await user.click(toggle());
  await user.click(toggle());

  expect(toggle()).toHaveAttribute("aria-expanded", "false");
});

test("the toggle controls the element that actually holds the filters", () => {
  // aria-controls pointing at the wrong element (or at nothing) is a silent
  // failure: it still reads as wired up.
  renderSidebar();
  const panelId = toggle().getAttribute("aria-controls");

  expect(panelId).toBeTruthy();
  const panel = document.getElementById(panelId!);
  expect(panel).not.toBeNull();
  expect(panel).toContainElement(screen.getByLabelText("Topic"));
});

test("applying filters collapses the panel", async () => {
  const user = userEvent.setup();
  renderSidebar();

  await user.click(toggle());
  await user.click(screen.getByRole("button", { name: /apply filters/i }));

  expect(toggle()).toHaveAttribute("aria-expanded", "false");
});

test("applying filters still reports the draft to the caller", async () => {
  // Collapsing must not swallow the apply -- the panel closing is worthless if the
  // search does not actually re-run.
  const user = userEvent.setup();
  const applied: SearchParams[] = [];
  renderSidebar({}, (p) => applied.push(p));

  await user.selectOptions(screen.getByLabelText("Evidence tier"), "emerging");
  await user.click(screen.getByRole("button", { name: /apply filters/i }));

  expect(applied).toEqual([{ tier: "emerging" }]);
});

test("the toggle reports how many filters are applied", () => {
  renderSidebar({ tier: "emerging", study_type: "rct" });

  expect(screen.getByRole("button", { name: "Filters, 2 applied" })).toBeInTheDocument();
});

test("the toggle reports nothing extra when no filters are applied", () => {
  renderSidebar({});

  expect(screen.getByRole("button", { name: "Filters" })).toBeInTheDocument();
});

test("the search query is not counted as a filter", () => {
  // `q` belongs to the search box above the results, not to this panel. Counting it
  // would report a filter that this panel cannot clear.
  renderSidebar({ q: "neural plasticity" });

  expect(screen.getByRole("button", { name: "Filters" })).toBeInTheDocument();
});

test("the count follows the applied filters, not the unapplied draft", async () => {
  // The count describes what is filtering the RESULTS. Choosing a value without
  // applying it changes nothing about them, so the count must not move yet --
  // otherwise it promises a filter that is not in effect.
  //
  // This has to diverge the draft from the applied value to mean anything: draft is
  // seeded from `value`, so any state where the user has not touched the form cannot
  // tell the two sources apart.
  const user = userEvent.setup();
  renderSidebar({});

  await user.selectOptions(screen.getByLabelText("Evidence tier"), "emerging");

  expect(screen.getByRole("button", { name: "Filters" })).toBeInTheDocument();
});

test("the count updates once the draft is applied", async () => {
  // The other half of the same rule: it must not be stuck, either.
  const user = userEvent.setup();
  function Harness() {
    const [applied, setApplied] = useState<SearchParams>({});
    return <FilterSidebar topics={TOPICS} value={applied} onApply={setApplied} />;
  }
  render(<Harness />);

  await user.selectOptions(screen.getByLabelText("Evidence tier"), "emerging");
  await user.click(screen.getByRole("button", { name: /apply filters/i }));

  expect(screen.getByRole("button", { name: "Filters, 1 applied" })).toBeInTheDocument();
});

test("every filter field counts", () => {
  renderSidebar({
    topic_id: "t1",
    tier: "emerging",
    study_type: "rct",
    date_from: "2026-01-01",
    date_to: "2026-06-01",
  });

  expect(screen.getByRole("button", { name: "Filters, 5 applied" })).toBeInTheDocument();
});
