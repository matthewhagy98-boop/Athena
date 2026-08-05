import { NavLink } from "react-router-dom";

const items = [
  { to: "/search", icon: "search", label: "Search" },
  { to: "/compare", icon: "compare_arrows", label: "Compare" },
  { to: "/saved-searches", icon: "bookmark", label: "Saved searches" },
];

export function IconSidebar() {
  // Per DESIGN.md responsive rules: the sidebar becomes a fixed bottom bar on
  // mobile (< md) so content keeps the full width.
  return (
    <nav className="flex w-14 shrink-0 flex-col items-center gap-1 bg-tertiary-container py-4 max-md:fixed max-md:bottom-0 max-md:z-10 max-md:h-14 max-md:w-full max-md:flex-row max-md:justify-center max-md:py-0">
      <div className="mb-4 flex h-7 w-7 items-center justify-center rounded bg-secondary text-sm font-bold text-on-secondary">
        A
      </div>
      {items.map((item) => (
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
