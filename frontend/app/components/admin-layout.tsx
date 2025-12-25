import { Activity, ChevronRight, FileText, Gamepad2, Image, LayoutDashboard } from "lucide-react";
import { Link, Outlet, useLocation, useParams } from "react-router";
import { cn } from "~/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
  exact?: boolean;
}

function NavLink({ to, label, icon, exact }: NavItem) {
  const location = useLocation();
  const isActive = exact ? location.pathname === to : location.pathname.startsWith(to);

  return (
    <Link
      to={to}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
        isActive
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {icon}
      {label}
    </Link>
  );
}

function Breadcrumbs() {
  const location = useLocation();
  const { id, resourceId, attachmentId } = useParams();
  const segments = location.pathname.split("/").filter(Boolean);

  const crumbs: { label: string; to: string }[] = [];

  for (let i = 0; i < segments.length; i++) {
    const segment = segments[i];
    const path = "/" + segments.slice(0, i + 1).join("/");

    if (segment === "admin") {
      crumbs.push({ label: "Admin", to: "/admin" });
    } else if (segment === "games" && segments[i - 1] === "admin") {
      // Skip - this is part of admin/games/:id
      if (segments[i + 1] === "new") {
        crumbs.push({ label: "New Game", to: path + "/new" });
        i++; // Skip 'new'
      } else if (id && segments[i + 1] === id) {
        crumbs.push({ label: "Game", to: `/admin/games/${id}` });
        i++; // Skip ID
      }
    } else if (segment === "resources" && id) {
      crumbs.push({ label: "Resources", to: `/admin/games/${id}/resources` });
      if (resourceId && segments[i + 1] === resourceId) {
        crumbs.push({
          label: "Resource",
          to: `/admin/games/${id}/resources/${resourceId}`,
        });
        i++; // Skip ID
      }
    } else if (segment === "attachments" && id) {
      crumbs.push({
        label: "Attachments",
        to: `/admin/games/${id}/attachments`,
      });
      if (attachmentId && segments[i + 1] === attachmentId) {
        crumbs.push({
          label: "Attachment",
          to: `/admin/games/${id}/attachments/${attachmentId}`,
        });
        i++; // Skip ID
      }
    }
  }

  return (
    <nav className="flex items-center gap-1 text-sm text-muted-foreground">
      {crumbs.map((crumb, i) => (
        <div key={crumb.to} className="flex items-center gap-1">
          {i > 0 && <ChevronRight className="h-4 w-4" />}
          {i === crumbs.length - 1 ? (
            <span className="text-foreground font-medium">{crumb.label}</span>
          ) : (
            <Link to={crumb.to} className="hover:text-foreground">
              {crumb.label}
            </Link>
          )}
        </div>
      ))}
    </nav>
  );
}

export function AdminLayout() {
  const { id } = useParams();

  const mainNav: NavItem[] = [
    {
      to: "/admin",
      label: "Dashboard",
      icon: <LayoutDashboard className="h-4 w-4" />,
      exact: true,
    },
    {
      to: "/admin/workflows",
      label: "Workflows",
      icon: <Activity className="h-4 w-4" />,
    },
  ];

  // Game-specific navigation when viewing a game
  const gameNav: NavItem[] = id
    ? [
        {
          to: `/admin/games/${id}`,
          label: "Game Details",
          icon: <Gamepad2 className="h-4 w-4" />,
          exact: true,
        },
        {
          to: `/admin/games/${id}/resources`,
          label: "Resources",
          icon: <FileText className="h-4 w-4" />,
        },
        {
          to: `/admin/games/${id}/attachments`,
          label: "Attachments",
          icon: <Image className="h-4 w-4" />,
        },
      ]
    : [];

  return (
    <div className="container mx-auto px-4 py-6">
      <div className="flex gap-6 min-h-[calc(100vh-12rem)]">
        {/* Sidebar */}
        <aside className="w-56 shrink-0">
          <nav className="space-y-6 sticky top-6">
            <div className="space-y-1">
              <h4 className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Main
              </h4>
              {mainNav.map((item) => (
                <NavLink key={item.to} {...item} />
              ))}
            </div>

            {gameNav.length > 0 && (
              <div className="space-y-1">
                <h4 className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Current Game
                </h4>
                {gameNav.map((item) => (
                  <NavLink key={item.to} {...item} />
                ))}
              </div>
            )}
          </nav>
        </aside>

        {/* Main content */}
        <main className="flex-1 min-w-0">
          <div className="mb-4">
            <Breadcrumbs />
          </div>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
