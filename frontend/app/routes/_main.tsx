import { Dices, Github } from "lucide-react";
import { Link, Outlet, useMatches } from "react-router";
import { Logo } from "~/components/logo";
import { useAuth } from "~/contexts/auth";

const GITHUB_URL = "https://github.com/dcramer/gamegame";

export default function MainLayout() {
  const { isAdmin } = useAuth();
  const matches = useMatches();

  // Check if any matched route has an "admin" handle or if path includes admin
  // useMatches is more reliable than useLocation for layout decisions
  const isOnAdminPage = matches.some(
    (match) => match.pathname.startsWith("/admin") || (match.handle as { admin?: boolean })?.admin,
  );

  return (
    <div className="min-h-screen flex flex-col">
      {/* Simple centered header for public pages - admin has its own header */}
      {!isOnAdminPage && (
        <header className="container mx-auto px-4 py-8">
          <Logo className="justify-center" />
        </header>
      )}

      <main
        className={isOnAdminPage ? "flex-1 flex flex-col" : "container mx-auto px-4 pb-12 flex-1"}
      >
        <Outlet />
      </main>

      {/* Footer - hide on admin pages since admin has its own layout */}
      {!isOnAdminPage && (
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
            {isAdmin && (
              <>
                <span>&middot;</span>
                <Link to="/admin" className="hover:underline">
                  Admin
                </Link>
              </>
            )}
          </div>
        </footer>
      )}
    </div>
  );
}
