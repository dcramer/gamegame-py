import type { Config } from "@react-router/dev/config";

export default {
  // Enable SSR
  ssr: true,

  // App directory (where routes live)
  appDirectory: "app",

  // Build output
  buildDirectory: "build",
} satisfies Config;
