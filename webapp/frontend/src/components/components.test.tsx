import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { PaperRow } from "../api/types";
import { CompareTray } from "./CompareTray";
import { EvidenceIndicator } from "./EvidenceIndicator";
import { ResearchCard } from "./ResearchCard";
import { TierSection } from "./TierSection";

const row: PaperRow = {
  paper: { id: "p1", title: "Neural plasticity study", abstract: "An abstract.", pub_date: "2024-11-02" },
  score: { evidence_tier: "established", study_type: "meta_analysis", final_score: 88 },
  topics: [{ id: "t1", canonical_label: "Cognitive mapping" }],
};

test("EvidenceIndicator maps final_score to filled steps", () => {
  render(<EvidenceIndicator finalScore={88} />);
  expect(screen.getByLabelText("Evidence strength 4 of 5")).toBeInTheDocument();
});

test("ResearchCard shows title, badge, topic link, and toggles selection", () => {
  const onToggle = vi.fn();
  render(
    <MemoryRouter>
      <ResearchCard row={row} checked={false} onToggleSelect={onToggle} />
    </MemoryRouter>,
  );
  expect(screen.getByText("Neural plasticity study")).toBeInTheDocument();
  expect(screen.getByText("meta analysis")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Cognitive mapping" })).toHaveAttribute("href", "/topics/t1");
  fireEvent.click(screen.getByRole("checkbox"));
  expect(onToggle).toHaveBeenCalledWith("p1");
});

test("TierSection shows empty state when no papers", () => {
  render(
    <MemoryRouter>
      <TierSection title="Speculation and hypotheses" papers={[]} emptyMessage="No speculative papers match." selectedIds={new Set()} onToggleSelect={() => {}} />
    </MemoryRouter>,
  );
  expect(screen.getByText("No speculative papers match.")).toBeInTheDocument();
  expect(screen.getByText("0 papers")).toBeInTheDocument();
});

test("CompareTray hides at zero and fires onCompare", () => {
  const onCompare = vi.fn();
  const { rerender } = render(<CompareTray count={0} onCompare={onCompare} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  rerender(<CompareTray count={2} onCompare={onCompare} />);
  fireEvent.click(screen.getByRole("button", { name: /compare \(2\)/i }));
  expect(onCompare).toHaveBeenCalled();
});
