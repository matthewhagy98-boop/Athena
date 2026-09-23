import { useActivityRanking, useChangeFeed, usePersonalDashboard } from "../api/hooks";
import { ActivityWidget } from "../components/ActivityWidget";
import { ChangeFeedWidget } from "../components/ChangeFeedWidget";
import { PersonalTopicsWidget } from "../components/PersonalTopicsWidget";
import { StalenessBanner } from "../components/StalenessBanner";
import { useIdentity } from "../identity/identity";

export function DashboardPage() {
  const { userId } = useIdentity();
  const activity = useActivityRanking();
  const changes = useChangeFeed();
  const personal = usePersonalDashboard(userId);

  return (
    <div>
      <h1 className="mb-4 text-2xl font-semibold">Dashboard</h1>

      <StalenessBanner computedAt={activity.data?.computed_at ?? null} />

      <div className="grid gap-4 lg:grid-cols-2">
        <ActivityWidget
          data={activity.data}
          isLoading={activity.isLoading}
          isError={activity.isError}
        />
        <ChangeFeedWidget
          data={changes.data}
          isLoading={changes.isLoading}
          isError={changes.isError}
        />
      </div>

      {/* Mounted only once the user has actually declared interests. Rendering an empty
          "your topics" panel for every first-time visitor would occupy the primary
          content area with a placeholder, which G-C-1 exists to prevent. */}
      {personal.data?.has_profile && (
        <div className="mt-4">
          <PersonalTopicsWidget
            data={personal.data}
            isLoading={personal.isLoading}
            isError={personal.isError}
          />
        </div>
      )}
    </div>
  );
}
