import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { IdentityProvider } from "../identity/identity";
import { server } from "../test/server";
import { InterestTopicPicker } from "./InterestTopicPicker";

const USER_ID = "00000000-0000-0000-0000-000000000001";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <IdentityProvider>{children}</IdentityProvider>
    </QueryClientProvider>
  );
}

function renderPicker() {
  // Setting the id in localStorage before render means IdentityProvider's initializer
  // picks it up synchronously, so no /users/anonymous request is needed for these tests.
  localStorage.setItem("athena_user_id", USER_ID);
  return render(<InterestTopicPicker />, { wrapper });
}

function submit(text: string) {
  fireEvent.change(screen.getByLabelText(/add a topic to follow/i), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /add/i }));
}

test("201: added confirms success and clears the input", async () => {
  server.use(
    http.post("/interests", () =>
      HttpResponse.json(
        { topic: { id: "t1", canonical_label: "Atrial fibrillation" }, created: true },
        { status: 201 },
      ),
    ),
  );
  renderPicker();

  submit("atrial fibrillation");

  await waitFor(() =>
    expect(screen.getByText(/added.*atrial fibrillation/i)).toBeInTheDocument(),
  );
  expect(screen.getByLabelText(/add a topic to follow/i)).toHaveValue("");
});

test("200: already an interest is stated plainly, not as an error", async () => {
  server.use(
    http.post("/interests", () =>
      HttpResponse.json(
        { topic: { id: "t1", canonical_label: "Atrial fibrillation" }, created: false },
        { status: 200 },
      ),
    ),
  );
  renderPicker();

  submit("atrial fibrillation");

  const message = await screen.findByText(/already one of your topics/i);
  expect(message).not.toHaveAttribute("role", "alert");
});

test("404: unknown user is framed as a stale identity, not bad input", async () => {
  server.use(http.post("/interests", () => HttpResponse.json({ detail: "not found" }, { status: 404 })));
  renderPicker();

  submit("atrial fibrillation");

  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/profile/i));
});

test("429: rate limited tells the user to retry later, never that their input was invalid", async () => {
  server.use(
    http.post("/interests", () => HttpResponse.json({ detail: "rate limited" }, { status: 429 })),
  );
  renderPicker();

  submit("atrial fibrillation");

  // Asserts what is UNIQUE to 429. The first version matched /try again/i, which the
  // generic fallback also says ("Something went wrong adding that topic. Try again.") --
  // so collapsing 429 into that fallback passed, and the state singled out as most
  // important to distinguish was the one state not actually pinned.
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(/added a lot of topics in the last hour/i),
  );
  const text = screen.getByRole("alert").textContent ?? "";
  expect(text).not.toMatch(/couldn't match|research topic|invalid|something went wrong/i);
});

test("422: an unresolved term is the only outcome described as about what was typed", async () => {
  server.use(http.post("/interests", () => HttpResponse.json({ detail: "no match" }, { status: 422 })));
  renderPicker();

  submit("zzzzzzzzzz");

  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/couldn't match/i));
});

test("the five outcomes each render distinct text", async () => {
  const messages: string[] = [];
  const cases: Array<[number, Record<string, unknown>]> = [
    [201, { topic: { id: "t1", canonical_label: "A" }, created: true }],
    [200, { topic: { id: "t1", canonical_label: "A" }, created: false }],
    [404, { detail: "not found" }],
    [429, { detail: "rate limited" }],
    [422, { detail: "no match" }],
  ];
  for (const [status, body] of cases) {
    server.use(http.post("/interests", () => HttpResponse.json(body, { status })));
    const { unmount } = renderPicker();
    submit("some term");
    await waitFor(() => {
      const alerts = screen.queryAllByRole("alert");
      const statuses = screen.queryAllByRole("status");
      expect(alerts.length + statuses.length).toBeGreaterThan(0);
    });
    const node = screen.queryByRole("alert") ?? screen.queryByRole("status");
    messages.push(node!.textContent ?? "");
    unmount();
  }
  expect(new Set(messages).size).toBe(messages.length);
});

test("the control is disabled while the add request is pending, and re-enabled after", async () => {
  let resolveRequest: (() => void) | undefined;
  server.use(
    http.post("/interests", async () => {
      await new Promise<void>((resolve) => {
        resolveRequest = resolve;
      });
      return HttpResponse.json(
        { topic: { id: "t1", canonical_label: "Atrial fibrillation" }, created: true },
        { status: 201 },
      );
    }),
  );
  renderPicker();

  submit("atrial fibrillation");

  await waitFor(() => expect(screen.getByRole("button", { name: /add/i })).toBeDisabled());
  expect(screen.getByLabelText(/add a topic to follow/i)).toBeDisabled();

  resolveRequest?.();

  // A successful 201 clears the input, so the button goes back to disabled for an
  // unrelated reason (nothing typed) -- checking the input's own disabled state and the
  // button's label reverting is what actually proves isPending cleared.
  await waitFor(() => expect(screen.getByRole("button", { name: /^add$/i })).toBeInTheDocument());
  expect(screen.getByLabelText(/add a topic to follow/i)).not.toBeDisabled();
});
