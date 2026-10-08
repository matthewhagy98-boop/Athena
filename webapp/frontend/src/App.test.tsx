import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach } from "vitest";
import App, { queryClient } from "./App";
import { server } from "./test/server";

beforeEach(() => {
  // App's QueryClient is a module singleton (matching production). Without clearing it,
  // a /features response cached by an earlier test in this file -- particularly the
  // disabled-flag override below -- would leak into the next test's render.
  queryClient.clear();
  localStorage.setItem("athena_user_id", "00000000-0000-0000-0000-000000000001");
  server.use(
    http.get("/search", () => HttpResponse.json({ rows: [], total: 0, page: 1, page_size: 50 })),
    http.get("/topics", () => HttpResponse.json([])),
  );
});

test("renders icon sidebar with the four nav destinations", async () => {
  // Awaits the features query. The Dashboard entry is gated and the sidebar fails
  // closed, so a synchronous assertion here would race the flag -- and an earlier draft
  // defaulted the entry to visible while pending purely to keep this test synchronous,
  // which bent the product to the test.
  render(<App />);

  await waitFor(() => expect(screen.getByLabelText("Dashboard")).toBeInTheDocument());
  for (const label of ["Search", "Compare", "Saved searches"]) {
    expect(screen.getByLabelText(label)).toBeInTheDocument();
  }
});

// Task 9: the dashboard is now the front door. This is the regression test for that
// change -- it fails if the root redirect is ever reverted to /search. Now async
// (Task 10): the redirect waits on the /features query, so it must be awaited rather
// than asserted synchronously.
test("default route redirects to the dashboard page", async () => {
  window.location.hash = "";
  render(<App />);
  await waitFor(() =>
    expect(screen.getByLabelText("Dashboard")).toHaveAttribute("aria-current", "page"),
  );
});

// /#/search must remain permanently valid even though it is no longer where "/" lands
// (the Playwright smoke test depends on this too).
test("/#/search still renders the search page directly", () => {
  window.location.hash = "#/search";
  render(<App />);
  expect(screen.getByLabelText("Search")).toHaveAttribute("aria-current", "page");
});

// Task 10: /#/dashboard must stay routable regardless of the flag -- someone with the
// link gets the page and its widgets' error states, which is honest.
test("/#/dashboard renders the dashboard page directly", async () => {
  window.location.hash = "#/dashboard";
  render(<App />);

  // Asserts the PAGE, not the nav item. The previous version checked the nav entry's
  // aria-current, which conflates routing with nav visibility -- and those deliberately
  // differ when the flag is off, so it contradicted the "routable either way" rule below.
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: /^dashboard$/i })).toBeInTheDocument(),
  );
});

test("/#/dashboard stays routable even with the flag off", async () => {
  // Someone testing the flag, or holding a direct link, gets the page and its widgets'
  // error states. Hiding the route would make the gate look like a bug.
  server.use(http.get("/features", () => HttpResponse.json({ dashboard_enabled: false })));
  window.location.hash = "#/dashboard";
  render(<App />);

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: /^dashboard$/i })).toBeInTheDocument(),
  );
  // ...but the nav entry is still gone, because the two are separate decisions.
  expect(screen.queryByLabelText("Dashboard")).toBeNull();
});

// Task 10: with the flag on, "/" still lands on the dashboard, and its nav entry is
// first among the sidebar's links.
test("with the dashboard flag on, the nav's first entry is Dashboard", async () => {
  window.location.hash = "";
  render(<App />);

  await waitFor(() => expect(screen.getByLabelText("Dashboard")).toHaveAttribute("aria-current", "page"));

  const links = screen.getAllByRole("link");
  expect(links[0]).toHaveAccessibleName("Dashboard");
});

// Task 10: DASHBOARD_ENABLED must fail closed. This file has produced three separate
// racing negative assertions before (see DashboardPage.test.tsx) -- each checked an
// absence before the state that would create it had arrived, and each passed against
// broken code. Guarding against the same shape here: the redirect to /search only
// happens once the /features query has resolved, so waiting for the search page to
// mount is itself proof the flag was read before we assert the nav's absence.
test("with the dashboard flag off, / lands on search and the nav omits Dashboard", async () => {
  server.use(http.get("/features", () => HttpResponse.json({ dashboard_enabled: false })));
  window.location.hash = "";
  render(<App />);

  await waitFor(() =>
    expect(screen.getByLabelText("Search")).toHaveAttribute("aria-current", "page"),
  );
  // Let react-query's cache notify every subscriber (the sidebar included) before
  // asserting what is NOT on screen -- same reasoning as DashboardPage.test.tsx's
  // extra tick after its own resolution wait.
  await new Promise((resolve) => setTimeout(resolve, 50));

  expect(screen.queryByLabelText("Dashboard")).not.toBeInTheDocument();
});

// Task 10: while the flag is unknown, "/" must render nothing rather than guessing --
// defaulting to the dashboard would show it to disabled users, and redirecting to
// /search first would flash the wrong page for every enabled user.
test("while the features query is pending, / renders neither page", () => {
  server.use(http.get("/features", () => new Promise(() => {}))); // never resolves
  window.location.hash = "";
  render(<App />);

  // The sidebar now fails closed too, so the Dashboard entry is absent rather than
  // present-but-unselected. Asserting not.toHaveAttribute on a null element passes
  // vacuously in jest-dom, so absence is asserted directly.
  expect(screen.queryByLabelText("Dashboard")).toBeNull();
  expect(screen.getByLabelText("Search")).not.toHaveAttribute("aria-current", "page");
});


test("an erroring /features lands on search promptly, not after the retry sequence", async () => {
  // RootRoute returned null while `isPending`, and react-query keeps isPending true across
  // the whole retry sequence -- so with /features down the landing page was blank for
  // about seven seconds, no spinner and no message, then redirected. It did fail closed,
  // but seven blank seconds reads as a broken deploy. On error the answer is already
  // known, so it is given immediately.
  server.use(http.get("/features", () => new HttpResponse(null, { status: 500 })));
  window.location.hash = "";
  const startedAt = Date.now();
  render(<App />);

  // The budget is the point of the test, so it is asserted rather than implied. With
  // react-query's default retry: 3 this took about seven seconds; useFeatures now sets
  // retry: 1, so one backoff then a decision.
  await waitFor(
    () => expect(screen.getByLabelText("Search")).toHaveAttribute("aria-current", "page"),
    // 4000, not 6000: vitest's default testTimeout is 5000, so a waitFor timeout above it
    // can never be reached -- the test dies first and the longer bound is dead. The
    // assertion below is 2000 anyway, so 4000 is ample headroom.
    { timeout: 4000 },
  );
  const elapsed = Date.now() - startedAt;
  // 2s is chosen to sit between the two policies, not as a round number: react-query's
  // default retry: 3 backs off 1s + 2s + 4s, so it cannot come in under 2s, while
  // retry: 1 backs off once and lands near 1s. A looser 4s budget passed under BOTH and
  // pinned nothing -- found by mutating the retry count back.
  expect(elapsed).toBeLessThan(2000);
  expect(screen.queryByLabelText("Dashboard")).not.toBeInTheDocument();
});


test("a /features body without the key fails closed at the root route", async () => {
  // The two existing flag-off tests both serve an explicit {dashboard_enabled: false},
  // which `?? true` or a truthiness check would leave untouched. Nothing exercised the
  // root route with a keyless body -- the hole the retry and string-truthiness findings
  // both sat in.
  server.use(http.get("/features", () => HttpResponse.json({})));
  window.location.hash = "";
  render(<App />);

  await waitFor(() => expect(screen.getByLabelText("Search")).toHaveAttribute("aria-current", "page"));
});


test('a stringly-typed "false" does not open the dashboard', async () => {
  // Both gates were truthiness checks, so any truthy non-boolean enabled the dashboard --
  // and "false" is truthy. Low likelihood against today's typed endpoint, but it is a
  // one-line fix for a gate whose stated rule is fail closed, and a stringly-typed flag is
  // exactly what a proxy, a mock, or a config-driven flags endpoint produces.
  server.use(http.get("/features", () => HttpResponse.json({ dashboard_enabled: "false" })));
  window.location.hash = "";
  render(<App />);

  await waitFor(() => expect(screen.getByLabelText("Search")).toHaveAttribute("aria-current", "page"));
  expect(screen.queryByLabelText("Dashboard")).not.toBeInTheDocument();
});
