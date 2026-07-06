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

test("renders icon sidebar with the three nav destinations", () => {
  render(<App />);
  expect(screen.getByLabelText("Search")).toBeInTheDocument();
  expect(screen.getByLabelText("Compare")).toBeInTheDocument();
  expect(screen.getByLabelText("Saved searches")).toBeInTheDocument();
});

test("default route redirects to the search page", () => {
  window.location.hash = "";
  render(<App />);
  expect(screen.getByLabelText("Search")).toHaveAttribute("aria-current", "page");
});
