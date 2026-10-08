# Collapsible filter panel on mobile

**Date:** 2026-09-17
**Status:** approved
**Surface:** `webapp/frontend/src/components/FilterSidebar.tsx` (search page)

## Why

Fixing the search page's horizontal overflow below 768px (commit `88388e0`) stacked
`FilterSidebar` above the results instead of beside them. That removed the overflow but
left the panel occupying the entire first screen on a phone: five controls and an Apply
button, with the first result pushed below the fold. The page's purpose is the results.

## Decisions

Settled with the user before implementation:

1. **Mobile only.** The panel collapses below Tailwind's `md` (768px). At `md` and above
   it stays the permanent 208px sidebar it is today. Desktop has the room, and
   `e2e/responsive-layout.spec.ts` already pins that design from the desktop side.
2. **Collapsed on first load.** Results are visible immediately; filters are one tap away.
3. **Applying collapses it.** You apply a filter to see its effect, so the results are
   what you should land on.
4. **The toggle carries a count of applied filters.** Not asked for, proposed and
   accepted: collapsing by default *hides* the fact that filters are active, so a user
   can land on filtered results with no visible reason why. The count restores that.

## Approach

React state plus Tailwind responsive classes — the idiom already used throughout this
codebase. Considered and rejected:

- **`<details>`/`<summary>`:** free disclosure semantics, but it cannot be forced open at
  `md` by media query alone; the `open` attribute has to be managed anyway, which gives
  up the simplicity that motivated it.
- **Open state in the URL:** survives reload and is shareable. No one asked for either.

## Design

`FilterSidebar` gains `const [open, setOpen] = useState(false)`. The `<aside>` keeps its
current responsive classes unchanged.

**Toggle button** — rendered `md:hidden`, so desktop never sees it. It replaces the
"Filters" heading on mobile and carries:

- `aria-expanded={open}` and `aria-controls` pointing at the panel body's id
- the label "Filters", plus the applied-filter count when that count is non-zero

**Panel body** — the existing controls, wrapped in a `<div id=...>` whose class is
`md:block` plus `block` when open and `hidden` when closed. At `md` and above `md:block`
always wins, so the desktop layout renders exactly as it does today regardless of state.

**Apply** — `onApply(draft)` is followed by `setOpen(false)`.

**The count** is derived from the *applied* params (`value`), not the local `draft`, so it
describes what is actually filtering the results rather than what the user is mid-way
through typing. It counts `topic_id`, `tier`, `study_type`, `date_from` and `date_to`.
It deliberately excludes `q`: that belongs to the search box above the results, not to
this panel, and counting it would report a filter the panel cannot clear.

## Testing

`e2e/responsive-layout.spec.ts` (real browser, 375px unless stated):

- the panel is collapsed on load, and the first result is visible without scrolling
- tapping the toggle reveals the controls
- applying a filter collapses the panel
- at 1280px there is no toggle and the controls are visible — the desktop guard

`FilterSidebar.test.tsx` (jsdom):

- the toggle reports `aria-expanded` correctly and it flips when activated
- `aria-controls` names the element that actually holds the controls
- the count reflects applied filters, ignores `q`, and is absent at zero

Every assertion is to be mutation-verified: a test that passes against a broken
implementation is a defect, not coverage.

## Out of scope

The panel's visual design, the filter set itself, and persisting the open state across
navigations.
