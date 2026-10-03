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

async function submit(text: string) {
  // The control is disabled until /features confirms the dashboard is on and identity
  // exists -- both gates fail closed, so clicking before they resolve does nothing. These
  // tests used to click immediately and pass only because the button was unconditionally
  // enabled; waiting here is what makes the click real.
  fireEvent.change(screen.getByLabelText(/add a topic to follow/i), { target: { value: text } });
  // Typing alone is not enough: the button is also gated on /features confirming the
  // dashboard is on and on identity existing, both of which fail closed while pending.
  await waitFor(() => expect(screen.getByRole("button", { name: /add/i })).toBeEnabled());
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

  await submit("atrial fibrillation");

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

  await submit("atrial fibrillation");

  const message = await screen.findByText(/already one of your topics/i);
  expect(message).not.toHaveAttribute("role", "alert");
});

test("404: unknown user is framed as a stale identity, not bad input", async () => {
  server.use(http.post("/interests", () => HttpResponse.json({ detail: "not found" }, { status: 404 })));
  renderPicker();

  await submit("atrial fibrillation");

  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/profile/i));
});

test("429: rate limited tells the user to retry later, never that their input was invalid", async () => {
  server.use(
    http.post("/interests", () => HttpResponse.json({ detail: "rate limited" }, { status: 429 })),
  );
  renderPicker();

  await submit("atrial fibrillation");

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

  await submit("zzzzzzzzzz");

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
    await submit("some term");
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

  await submit("atrial fibrillation");

  await waitFor(() => expect(screen.getByRole("button", { name: /add/i })).toBeDisabled());
  expect(screen.getByLabelText(/add a topic to follow/i)).toBeDisabled();

  resolveRequest?.();

  // A successful 201 clears the input, so the button goes back to disabled for an
  // unrelated reason (nothing typed) -- checking the input's own disabled state and the
  // button's label reverting is what actually proves isPending cleared.
  await waitFor(() => expect(screen.getByRole("button", { name: /^add$/i })).toBeInTheDocument());
  expect(screen.getByLabelText(/add a topic to follow/i)).not.toBeDisabled();
});


test("the control is inert-but-explained before identity exists, never silently inert", async () => {
  // Previously: the button stayed enabled with no identity, so the user typed, pressed
  // Add, and absolutely nothing happened -- no request, no message, no disabled state.
  // Reachable on a first visit while POST /users/anonymous is in flight, and permanently
  // if it fails.
  let requests = 0;
  server.use(http.post("/interests", () => {
    requests += 1;
    return HttpResponse.json({ topic: { id: "t1", canonical_label: "A" }, created: true }, { status: 201 });
  }));
  localStorage.removeItem("athena_user_id");
  server.use(http.post("/users/anonymous", () => new Promise(() => {})));  // never resolves
  render(<InterestTopicPicker />, { wrapper });

  fireEvent.change(screen.getByLabelText(/add a topic to follow/i), { target: { value: "sepsis" } });
  fireEvent.click(screen.getByRole("button", { name: /add/i }));

  await waitFor(() => expect(screen.getByRole("button", { name: /add/i })).toBeDisabled());
  expect(requests).toBe(0);
});

test("with the dashboard disabled the picker says so, instead of telling the user to reload", async () => {
  // /#/dashboard stays routable with the flag off by design, so the picker is reachable
  // and POST /interests returns 404 -- which the 404 branch reports as a stale profile
  // and advises reloading. Reloading can never fix it. The two cases are
  // indistinguishable in the response on purpose, so the picker has to read /features.
  server.use(http.get("/features", () => HttpResponse.json({ dashboard_enabled: false })));
  renderPicker();

  await waitFor(() =>
    expect(screen.getByText(/isn't available on this deployment/i)).toBeInTheDocument(),
  );
  expect(screen.getByRole("button", { name: /add/i })).toBeDisabled();
  expect(screen.queryByText(/reloading the page/i)).not.toBeInTheDocument();
});

test("a 500 still says something, rather than re-enabling the button in silence", async () => {
  // The generic onError fallback had no test: deleting it produced NO feedback at all for
  // a 5xx, and the five covered cases are 201/200/404/429/422.
  server.use(http.post("/interests", () => new HttpResponse(null, { status: 500 })));
  renderPicker();

  await submit("sepsis");

  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/something went wrong/i));
});
