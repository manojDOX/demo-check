import { useQuery } from "@tanstack/react-query";
import { useAuth } from "./use-auth";

interface RoleInfo {
  role: "admin" | "viewer";
  adminUserId?: string;
  teamMemberId?: number;
  allowedClientIds?: number[];
}

export function useRole() {
  const { isAuthenticated } = useAuth();

  const { data, isLoading } = useQuery<RoleInfo>({
    queryKey: ["/api/auth/role"],
    enabled: isAuthenticated,
    staleTime: 1000 * 60 * 5,
  });

  return {
    role: data?.role || "admin",
    isAdmin: !data || data.role === "admin",
    isViewer: data?.role === "viewer",
    allowedClientIds: data?.allowedClientIds || [],
    adminUserId: data?.adminUserId,
    teamMemberId: data?.teamMemberId,
    isLoading,
  };
}
