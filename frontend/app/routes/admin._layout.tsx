import { AdminLayout } from "~/components/admin-layout";
import { ProtectedRoute } from "~/components/protected-route";

export default function AdminLayoutRoute() {
  return (
    <ProtectedRoute requireAdmin>
      <AdminLayout />
    </ProtectedRoute>
  );
}
