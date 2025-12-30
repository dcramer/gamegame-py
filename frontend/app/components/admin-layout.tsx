import { Dices, Github } from "lucide-react";
import { Link, NavLink, Outlet } from "react-router";
import { cn } from "~/lib/utils";
import { Logo } from "./logo";

const GITHUB_URL = "https://github.com/dcramer/gamegame";

/**
 * Admin layout with header and simple navigation.
 */
export function AdminLayout() {
  return (
    <div className="flex flex-col flex-1">
      {/* Header */}
      <header className="border-b border-border">
        <div className="container mx-auto px-4 py-4">
          {/* Logo + Admin nav */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Logo size="sm" />
              <span className="text-muted-foreground">/</span>
              <Link
                to="/admin"
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                admin
              </Link>
            </div>
            <nav className="flex items-center gap-1">
              <NavLink
                to="/admin"
                end
                className={({ isActive }) =>
                  cn(
                    "px-3 py-1.5 text-sm rounded-md transition-colors",
                    isActive
                      ? "bg-muted text-foreground font-medium"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
                  )
                }
              >
                Dashboard
              </NavLink>
              <NavLink
                to="/admin/workflows"
                className={({ isActive }) =>
                  cn(
                    "px-3 py-1.5 text-sm rounded-md transition-colors",
                    isActive
                      ? "bg-muted text-foreground font-medium"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
                  )
                }
              >
                Workflows
              </NavLink>
            </nav>
          </div>
        </div>
      </header>

      {/* Main content */}
      <div className="container mx-auto px-4 py-6 flex-1">
        <Outlet />
      </div>

      {/* Footer */}
      <footer className="container mx-auto px-4 py-8 text-center text-muted-foreground font-mono text-xs">
        <div className="flex justify-center items-center gap-4">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 hover:underline"
          >
            <Github className="w-4 h-4" />
            GitHub
          </a>
          <span>&middot;</span>
          <Link to="/" className="flex items-center gap-1 hover:underline">
            <Dices className="w-4 h-4" />
            GameGame
          </Link>
          <span>&middot;</span>
          <Link to="/admin" className="hover:underline">
            Admin
          </Link>
        </div>
      </footer>
    </div>
  );
}
