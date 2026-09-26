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
// it to disabled ones. So while the flag is unknown (query pending), render nothing --
// `data` stays undefined on error too, which naturally falls back to /search.
function RootRoute() {
  const { data, isPending } = useFeatures();
  if (isPending) return null;
  return <Navigate to={data?.dashboard_enabled ? "/dashboard" : "/search"} replace />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <IdentityProvider>
        <HashRouter>
          <div className="flex min-h-screen">
            <IconSidebar />
            <main className="mx-auto w-full max-w-[1200px] flex-1 px-12 py-8">
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
