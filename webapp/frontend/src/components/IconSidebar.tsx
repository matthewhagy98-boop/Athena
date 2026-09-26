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
  // DASHBOARD_ENABLED (Task 10): a nav item leading to a page whose data all 503s is
  // worse than no nav item, so the entry is omitted once the flag resolves false.
  // Defaults to shown while the query is still pending -- unlike the root route, a
  // briefly-visible nav item carries no navigation risk, and the sidebar mounts
  // instantly on every page, so failing closed here would flash it away on every load.
  const { data } = useFeatures();
  const dashboardEnabled = data?.dashboard_enabled ?? true;
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
