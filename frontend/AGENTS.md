# Frontend AGENTS.md

This file provides guidance for AI assistants working on the React frontend.

## Quick Reference

```bash
# Development
cd frontend
npm run dev           # Start dev server (http://localhost:5173)

# Build
npm run build         # Production build
npm run preview       # Preview production build

# Code Quality
npm run lint          # ESLint
npm run format        # Prettier
npm run typecheck     # TypeScript check
```

## Project Structure

```
frontend/
├── src/
│   ├── main.tsx              # Entry point, React Router setup
│   ├── App.tsx               # Route definitions
│   │
│   ├── api/
│   │   ├── client.ts         # API client with auth handling
│   │   └── types.ts          # TypeScript types (match backend schemas)
│   │
│   ├── components/
│   │   ├── layout.tsx        # Main layout with header/footer
│   │   └── ui/               # Radix UI components
│   │
│   ├── pages/
│   │   ├── home.tsx
│   │   ├── games.tsx         # Games list
│   │   ├── game.tsx          # Game detail + chat
│   │   ├── auth/
│   │   │   └── signin.tsx
│   │   └── admin/            # Admin pages
│   │
│   ├── hooks/                # Custom React hooks
│   ├── lib/
│   │   └── utils.ts          # cn() and utilities
│   └── styles/
│       └── globals.css       # Tailwind CSS
│
├── public/                   # Static assets
├── index.html
├── vite.config.ts
├── tsconfig.json
└── package.json
```

## Key Patterns

### API Client Usage

```typescript
import { api } from "@/api/client";

// List games
const games = await api.games.list();

// Get single game
const game = await api.games.get("game-slug");

// Create (requires auth)
const newGame = await api.games.create({ name: "New Game" });

// Update
await api.games.update(id, { name: "Updated" });

// Delete
await api.games.delete(id);
```

### Authentication

```typescript
import { api, setAuthToken, getAuthToken } from "@/api/client";

// Login flow
const { magic_link } = await api.auth.login("user@example.com");

// After clicking magic link, verify token
const { access_token, user } = await api.auth.verify(token);
setAuthToken(access_token);

// Get current user
const user = await api.auth.me();

// Logout
await api.auth.logout();
setAuthToken(null);
```

### React Router

```typescript
import { Routes, Route, Link, useParams, useNavigate } from "react-router";

// Navigation
<Link to="/games">Games</Link>
<Link to={`/games/${game.slug}`}>{game.name}</Link>

// Get params
const { gameIdOrSlug } = useParams<{ gameIdOrSlug: string }>();

// Programmatic navigation
const navigate = useNavigate();
navigate("/games");
```

### Data Fetching Pattern

```typescript
import { useState, useEffect } from "react";
import { api } from "@/api/client";

export function GamesPage() {
  const [games, setGames] = useState<Game[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadGames() {
      try {
        const data = await api.games.list();
        setGames(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    }
    loadGames();
  }, []);

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="text-destructive">Error: {error}</p>;

  return <GamesList games={games} />;
}
```

### Tailwind CSS

```typescript
// Use cn() utility for conditional classes
import { cn } from "@/lib/utils";

<button
  className={cn(
    "px-4 py-2 rounded-lg font-medium",
    "bg-primary text-primary-foreground",
    "hover:opacity-90 transition-opacity",
    disabled && "opacity-50 cursor-not-allowed"
  )}
>
  Click me
</button>

// Common patterns
<div className="container mx-auto px-4 py-8">
<div className="max-w-2xl mx-auto">
<div className="flex items-center gap-4">
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
```

### Form Handling

```typescript
import { useState } from "react";

export function LoginForm() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await api.auth.login(email);
      // Show success message
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
      />
      {error && <p className="text-destructive">{error}</p>}
      <button type="submit" disabled={loading}>
        {loading ? "Loading..." : "Submit"}
      </button>
    </form>
  );
}
```

## TypeScript Types

Keep types in sync with backend schemas:

```typescript
// api/types.ts
export interface User {
  id: number;
  email: string;
  name: string | null;
  is_admin: boolean;
}

export interface Game {
  id: number;
  name: string;
  slug: string;
  year: number | null;
  image_url: string | null;
  description: string | null;
}

export interface Resource {
  id: number;
  game_id: number;
  name: string;
  status: "ready" | "queued" | "processing" | "completed" | "failed";
  resource_type: "rulebook" | "expansion" | "faq" | "errata" | "reference";
}
```

## Styling

### Tailwind CSS 4

Using Tailwind CSS v4 with the Vite plugin:

```css
/* globals.css */
@import "tailwindcss";

@theme {
  --color-background: #ffffff;
  --color-foreground: #0a0a0a;
  --color-primary: #171717;
  --color-primary-foreground: #fafafa;
  /* ... */
}
```

### Color Variables

- `bg-background` / `text-foreground` - Main colors
- `bg-primary` / `text-primary-foreground` - Buttons, accents
- `bg-muted` / `text-muted-foreground` - Secondary text
- `border-border` - Borders
- `text-destructive` - Errors

## Component Library

Using Radix UI primitives. Components should be in `components/ui/`:

```typescript
// components/ui/button.tsx
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  asChild?: boolean;
  variant?: "default" | "outline" | "ghost";
}

export function Button({
  className,
  variant = "default",
  asChild = false,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      className={cn(
        "px-4 py-2 rounded-lg font-medium transition-colors",
        variant === "default" && "bg-primary text-primary-foreground",
        variant === "outline" && "border border-border",
        variant === "ghost" && "hover:bg-muted",
        className
      )}
      {...props}
    />
  );
}
```

## Vite Configuration

```typescript
// vite.config.ts
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Proxy API requests to backend
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
```

## Common Issues

### API requests fail in development
Vite proxies `/api` requests to `localhost:8000`. Make sure backend is running.

### TypeScript path aliases not working
Check `tsconfig.json` has `paths` configured and Vite has matching `resolve.alias`.

### Styles not applying
Make sure `globals.css` is imported in `main.tsx`.
