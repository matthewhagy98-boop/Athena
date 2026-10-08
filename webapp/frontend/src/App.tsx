import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { useFeatures } from "./api/hooks";
import { IconSidebar } from "./components/IconSidebar";
import { SearchPage } from "./pages/SearchPage";
import { ComparePage } from "./pages/ComparePage";
import { SavedSearchesPage } from "./pages/SavedSearchesPage";
import { TopicDetailPage } from "./pages/TopicDetailPage";
import { DashboardPage } from "./pages/DashboardPage";
import { IdentityProvider } from "./identity/identity";

// Exported so tests can clear cached query results between cases -- this is a module
// singleton (matching production, where App renders once), so without a reset here a
// /features response cached by one test would leak into the next.
export const queryClient = new QueryClient();

// DASHBOARD_ENABLED (Task 10) gates whether "/" lands on the dashboard or on search.
// This must fail closed: redirecting to /search first and correcting afterwards would
// flash the wrong page for every enabled user, and defaulting to /dashboard would show
// it to disabled ones. So while the flag is unknown, render nothing.
//
// With /features returning 500 this page stayed blank for about seven seconds -- no
// spinner, no message -- and then redirected. It did fail closed, but seven blank seconds
// reads as a broken deploy. The cause was react-query's default `retry: 3` with
// exponential backoff (1s + 2s + 4s), during all of which `isPending` stays true; the fix
// is `retry: 1` on useFeatures, and the test asserts the resulting budget directly.
//
// Note `isPending` alone is the right condition. An earlier version of this fix added
// `&& !isError`, which a mutation showed to be dead code: in react-query v5 pending and
// error are mutually exclusive, so by the time isError is true isPending is already false.
// It read like a safety net and could never fire.
//
// `=== true` rather than a truthiness check: the rule here is fail closed, and any truthy
// non-boolean -- the string "false" from a proxy, a mock, or a future config-driven flags
// endpoint -- would otherwise open the dashboard.
function RootRoute() {
  const { data, isPending } = useFeatures();
  if (isPending) return null;
  return <Navigate to={data?.dashboard_enabled === true ? "/dashboard" : "/search"} replace />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <IdentityProvider>
        <HashRouter>
          <div className="flex min-h-screen">
            <IconSidebar />
            {/* px-12 is 96px of padding -- a quarter of a 375px phone screen, spent
                before any content. Below the `md` breakpoint (where IconSidebar
                becomes a bottom bar) it drops to px-4. */}
            <main className="mx-auto w-full max-w-[1200px] flex-1 px-4 py-8 md:px-12">
              <Routes>
                <Route path="/" element={<RootRoute />} />
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/search" element={<SearchPage />} />
                <Route path="/compare" element={<ComparePage />} />
                <Route path="/saved-searches" element={<SavedSearchesPage />} />
                <Route path="/topics/:topicId" element={<TopicDetailPage />} />
              </Routes>
            </main>
          </div>
        </HashRouter>
      </IdentityProvider>
    </QueryClientProvider>
  );
}
