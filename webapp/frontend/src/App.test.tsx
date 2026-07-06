import { render, screen } from "@testing-library/react";
import { beforeEach } from "vitest";
import App from "./App";

beforeEach(() => localStorage.setItem("athena_user_id", "00000000-0000-0000-0000-000000000001"));

test("renders icon sidebar with the three nav destinations", () => {
  render(<App />);
  expect(screen.getByLabelText("Search")).toBeInTheDocument();
  expect(screen.getByLabelText("Compare")).toBeInTheDocument();
  expect(screen.getByLabelText("Saved searches")).toBeInTheDocument();
});

test("default route redirects to the search page", () => {
  window.location.hash = "";
  render(<App />);
  expect(screen.getByRole("heading", { name: /search/i })).toBeInTheDocument();
});
