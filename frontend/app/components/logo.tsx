import { Dices } from "lucide-react";
import { Link } from "react-router";
import { cn } from "~/lib/utils";

interface LogoProps {
  /**
   * Size variant for the logo
   * @default "default"
   */
  size?: "sm" | "default" | "lg";
  /**
   * Optional className to apply to the container
   */
  className?: string;
}

/**
 * GameGame logo component with link to home page
 */
export function Logo({ size = "default", className }: LogoProps) {
  const iconClass = size === "sm" ? "w-6 h-6" : "w-8 h-8";
  const textClass = size === "sm" ? "text-xl lg:text-2xl" : "text-2xl lg:text-4xl";

  return (
    <Link to="/" className={cn("flex items-center space-x-2", className)}>
      <Dices className={cn(iconClass)} />
      <h1 className={cn("font-bold", textClass)}>gamegame</h1>
    </Link>
  );
}
