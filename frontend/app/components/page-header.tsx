import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { cn } from "~/lib/utils";

export interface BreadcrumbItem {
  label: string;
  to?: string;
}

export interface PageHeaderProps {
  /**
   * Breadcrumb items for navigation hierarchy
   */
  breadcrumbs?: BreadcrumbItem[];

  /**
   * Page title (required) - can be a string or a React node
   */
  title: string | ReactNode;

  /**
   * Optional description or subtitle
   */
  description?: string;

  /**
   * Optional stats or metadata (e.g., "5 resources - 120 pages")
   */
  stats?: string;

  /**
   * Action buttons to display on the right side
   */
  actions?: ReactNode;

  /**
   * Additional CSS classes for the container
   */
  className?: string;
}

/**
 * Breadcrumb navigation component
 */
function Breadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  if (items.length === 0) return null;

  return (
    <nav className="flex items-center gap-2 text-sm text-muted-foreground mb-4">
      {items.map((item, index) => {
        const isLast = index === items.length - 1;

        return (
          <div key={index} className="flex items-center gap-2">
            {item.to && !isLast ? (
              <Link to={item.to} className="hover:text-foreground transition-colors">
                {item.label}
              </Link>
            ) : (
              <span className={isLast ? "text-foreground font-medium" : ""}>{item.label}</span>
            )}

            {!isLast && <ChevronRight className="h-4 w-4" />}
          </div>
        );
      })}
    </nav>
  );
}

/**
 * Standard page header component for admin pages
 *
 * Provides consistent layout for:
 * - Breadcrumb navigation
 * - Page title
 * - Description/subtitle
 * - Stats/metadata
 * - Action buttons
 *
 * @example
 * <PageHeader
 *   breadcrumbs={[
 *     { label: 'Admin', to: '/admin' },
 *     { label: 'Games' }
 *   ]}
 *   title="Games"
 *   actions={<Button asChild><Link to="/admin/games/new">Add Game</Link></Button>}
 * />
 */
export function PageHeader({
  breadcrumbs,
  title,
  description,
  stats,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <div className={cn("mb-6", className)}>
      {breadcrumbs && breadcrumbs.length > 0 && <Breadcrumbs items={breadcrumbs} />}

      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <h1 className="text-3xl font-bold tracking-tight">{title}</h1>

          {description && <p className="mt-1 text-muted-foreground max-w-3xl">{description}</p>}

          {stats && <p className="mt-1 text-sm text-muted-foreground">{stats}</p>}
        </div>

        {actions && <div className="flex items-center gap-2 flex-shrink-0">{actions}</div>}
      </div>
    </div>
  );
}
