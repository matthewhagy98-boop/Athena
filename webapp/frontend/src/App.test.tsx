import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach } from "vitest";
import App from "./App";
import { server } from "./test/server";

beforeEach(() => {
  localStorage.setItem("athena_user_id", "00000000-0000-0000-0000-000000000001");
  server.use(
    http.get("/search", () => HttpResponse.json({ rows: [], total: 0, page: 1, page_size: 50 })),
    http.get("/topics", () => HttpResponse.json([])),
  );
});

test("renders icon sidebar with the four nav destinations", () => {
  render(<App />);
  expect(screen.getByLabelText("Dashboard")).toBeInTheDocument();
  expect(screen.getByLabelText("Search")).toBeInTheDocument();
  expect(screen.getByLabelText("Compare")).toBeInTheDocument();
  expect(screen.getByLabelText("Saved searches")).toBeInTheDocument();
});

// Task 9: the dashboard is now the front door. This is the regression test for that
// change -- it fails if the root redirect is ever reverted to /search.
test("default route redirects to the dashboard page", () => {
  window.location.hash = "";
  render(<App />);
  expect(screen.getByLabelText("Dashboard")).toHaveAttribute("aria-current", "page");
});

// /#/search must remain permanently valid even though it is no longer where "/" lands
// (the Playwright smoke test depends on this too).
test("/#/search still renders the search page directly", () => {
  window.location.hash = "#/search";
  render(<App />);
  expect(screen.getByLabelText("Search")).toHaveAttribute("aria-current", "page");
});
