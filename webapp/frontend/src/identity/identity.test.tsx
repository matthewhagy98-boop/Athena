import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { IdentityProvider, useIdentity } from "./identity";

function Probe() {
  const { userId, error } = useIdentity();
  return <div>{error ? "error" : (userId ?? "loading")}</div>;
}

test("creates an anonymous user on first visit and persists it", async () => {
  server.use(
    http.post("/users/anonymous", () => HttpResponse.json({ user_id: "abc-123" }, { status: 201 })),
  );
  render(
    <IdentityProvider>
      <Probe />
    </IdentityProvider>,
  );
  await waitFor(() => expect(screen.getByText("abc-123")).toBeInTheDocument());
  expect(localStorage.getItem("athena_user_id")).toBe("abc-123");
});

test("reuses a stored user id without calling the API", () => {
  localStorage.setItem("athena_user_id", "stored-id");
  render(
    <IdentityProvider>
      <Probe />
    </IdentityProvider>,
  );
  expect(screen.getByText("stored-id")).toBeInTheDocument();
});

test("reports an error when creation fails", async () => {
  server.use(http.post("/users/anonymous", () => HttpResponse.text("boom", { status: 500 })));
  render(
    <IdentityProvider>
      <Probe />
    </IdentityProvider>,
  );
  await waitFor(() => expect(screen.getByText("error")).toBeInTheDocument());
});
