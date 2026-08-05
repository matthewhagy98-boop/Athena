import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { IconSidebar } from "./components/IconSidebar";
import { SearchPage } from "./pages/SearchPage";
import { ComparePage } from "./pages/ComparePage";
import { SavedSearchesPage } from "./pages/SavedSearchesPage";
import { TopicDetailPage } from "./pages/TopicDetailPage";
import { IdentityProvider } from "./identity/identity";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <IdentityProvider>
        <HashRouter>
          <div className="flex min-h-screen">
            <IconSidebar />
            <main className="mx-auto w-full max-w-[1200px] flex-1 px-12 py-8">
              <Routes>
                <Route path="/" element={<Navigate to="/search" replace />} />
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
