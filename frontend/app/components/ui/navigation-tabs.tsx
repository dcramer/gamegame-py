import * as React from "react";
import { Link, useLocation } from "react-router";
import { cn } from "~/lib/utils";
import { Badge } from "./badge";

/**
 * Navigation tabs for use with React Router Link components.
 * These tabs rely on URL-based state and work with React Router routing.
 *
 * @example
 * ```tsx
 * <NavigationTabs>
 *   <NavigationTabsList>
 *     <NavigationTabsLink to="/game/123" end>Details</NavigationTabsLink>
 *     <NavigationTabsLink to="/game/123/resources">
 *       Resources <NavigationTabsBadge>5</NavigationTabsBadge>
 *     </NavigationTabsLink>
 *   </NavigationTabsList>
 *   <NavigationTabsContent>{children}</NavigationTabsContent>
 * </NavigationTabs>
 * ```
 */

const NavigationTabs = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("w-full", className)} {...props} />
  ),
);
NavigationTabs.displayName = "NavigationTabs";

const NavigationTabsList = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      role="tablist"
      className={cn("flex items-center gap-6 border-b border-border", className)}
      {...props}
    />
  ),
);
NavigationTabsList.displayName = "NavigationTabsList";

interface NavigationTabsLinkProps extends Omit<React.ComponentProps<typeof Link>, "className"> {
  /**
   * If true, only match when the path is exactly equal (like NavLink's "end" prop)
   */
  end?: boolean;
  className?: string;
  children: React.ReactNode;
}

/**
 * A tab trigger that uses React Router Link and automatically determines active state
 */
function NavigationTabsLink({
  to,
  end = false,
  className,
  children,
  ...props
}: NavigationTabsLinkProps) {
  const location = useLocation();
  const toPath = typeof to === "string" ? to : to.pathname || "";

  // Determine if this tab is active
  const isActive = end ? location.pathname === toPath : location.pathname.startsWith(toPath);

  return (
    <Link
      to={to}
      role="tab"
      aria-selected={isActive}
      className={cn(
        "inline-flex items-center gap-2 whitespace-nowrap px-1 pb-3 text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 border-b-2 -mb-[1px]",
        isActive
          ? "text-foreground border-primary"
          : "text-muted-foreground border-transparent hover:text-foreground hover:border-border",
        className,
      )}
      {...props}
    >
      {children}
    </Link>
  );
}
NavigationTabsLink.displayName = "NavigationTabsLink";

interface NavigationTabsTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /**
   * Whether this tab is currently active.
   * Usually determined from the current route pathname.
   */
  active?: boolean;
}

/**
 * A manual tab trigger (for cases where you need custom active logic)
 */
const NavigationTabsTrigger = React.forwardRef<HTMLButtonElement, NavigationTabsTriggerProps>(
  ({ className, active, ...props }, ref) => (
    <button
      ref={ref}
      role="tab"
      aria-selected={active}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap px-1 pb-3 text-sm font-medium transition-all cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 border-b-2 -mb-[1px]",
        active
          ? "text-foreground border-primary"
          : "text-muted-foreground border-transparent hover:text-foreground hover:border-border",
        className,
      )}
      {...props}
    />
  ),
);
NavigationTabsTrigger.displayName = "NavigationTabsTrigger";

const NavigationTabsContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    role="tabpanel"
    className={cn(
      "mt-6 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
      className,
    )}
    {...props}
  />
));
NavigationTabsContent.displayName = "NavigationTabsContent";

/**
 * Badge to show counts in tab labels
 */
function NavigationTabsBadge({ children }: { children: React.ReactNode }) {
  return (
    <Badge variant="secondary" className="text-xs px-1.5 py-0 h-5 min-w-5">
      {children}
    </Badge>
  );
}
NavigationTabsBadge.displayName = "NavigationTabsBadge";

export {
  NavigationTabs,
  NavigationTabsList,
  NavigationTabsLink,
  NavigationTabsTrigger,
  NavigationTabsContent,
  NavigationTabsBadge,
};
