import { NavLink } from "react-router-dom";
import { useFeatures } from "../api/hooks";

const DASHBOARD_ITEM = { to: "/dashboard", icon: "dashboard", label: "Dashboard" };

const items = [
  DASHBOARD_ITEM,
  { to: "/search", icon: "search", label: "Search" },
  { to: "/compare", icon: "compare_arrows", label: "Compare" },
  { to: "/saved-searches", icon: "bookmark", label: "Saved searches" },
];

export function IconSidebar() {
  // DASHBOARD_ENABLED (Task 10): a nav item leading to a page whose data all 404s is
  // worse than no nav item, so the entry is omitted unless the flag resolves true.
  //
  // Fails CLOSED, like the root route. The first draft defaulted to shown while the
  // query was pending, to keep a synchronous test passing -- but that is bending the
  // product to the test. It also briefly advertises a gated feature on every fresh load
  // of a disabled deployment, which is the one thing the gate exists to prevent.
  //
  // The cost is the mirror image: on an enabled deployment the entry appears a moment
  // after first paint. That happens once per session, not per navigation -- useFeatures
  // is a cached react-query, so only the first mount is ever pending -- and an entry
  // arriving late is a smaller wrong than an entry that should not exist at all.
  const { data } = useFeatures();
  // `=== true`, not `?? false`: both fail closed on a missing key, but only this one
  // fails closed on a truthy non-boolean. `{"dashboard_enabled": "false"}` from a proxy,
  // a mock, or a future config-driven flags endpoint would otherwise show the entry.
  const dashboardEnabled = data?.dashboard_enabled === true;
  const visibleItems = items.filter((item) => item !== DASHBOARD_ITEM || dashboardEnabled);

  // Per DESIGN.md responsive rules: the sidebar becomes a fixed bottom bar on
  // mobile (< md) so content keeps the full width.
  return (
    <nav className="flex w-14 shrink-0 flex-col items-center gap-1 bg-tertiary-container py-4 max-md:fixed max-md:bottom-0 max-md:z-10 max-md:h-14 max-md:w-full max-md:flex-row max-md:justify-center max-md:py-0">
      <div className="mb-4 flex h-7 w-7 items-center justify-center rounded bg-secondary text-sm font-bold text-on-secondary">
        A
      </div>
      {visibleItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          aria-label={item.label}
          title={item.label}
          className={({ isActive }) =>
            `flex h-9 w-9 items-center justify-center rounded ${
              isActive
                ? "border-l-2 border-secondary-container bg-primary-container text-secondary-container"
                : "text-on-tertiary-container hover:text-secondary-container"
            }`
          }
        >
          <span className="material-symbols-outlined text-[18px]" aria-hidden="true">{item.icon}</span>
        </NavLink>
      ))}
    </nav>
  );
}
