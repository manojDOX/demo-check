import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { User } from "@shared/models/auth";

async function fetchUser(): Promise<User | null> {
  const response = await fetch("/api/auth/user", {
    credentials: "include",
  });

  if (response.ok) {
    return response.json();
  }

  const tokenResponse = await fetch("/api/auth/token-session", {
    credentials: "include",
  });

  if (tokenResponse.ok) {
    const data = await tokenResponse.json();
    if (data.authenticated) {
      return {
        id: `token-${data.teamMemberId}`,
        email: data.email,
        firstName: data.email.split("@")[0],
        lastName: "",
        profileImageUrl: null,
        createdAt: new Date(),
        updatedAt: new Date(),
      } as User;
    }
  }

  return null;
}

async function logout(): Promise<void> {
  const tokenResponse = await fetch("/api/auth/token-session", {
    credentials: "include",
  });
  if (tokenResponse.ok) {
    const data = await tokenResponse.json();
    if (data.authenticated) {
      window.location.href = "/api/shared/logout";
      return;
    }
  }
  window.location.href = "/api/logout";
}

export function useAuth() {
  const queryClient = useQueryClient();
  const { data: user, isLoading } = useQuery<User | null>({
    queryKey: ["/api/auth/user"],
    queryFn: fetchUser,
    retry: false,
    staleTime: 1000 * 60 * 5,
  });

  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.setQueryData(["/api/auth/user"], null);
    },
  });

  return {
    user,
    isLoading,
    isAuthenticated: !!user,
    logout: logoutMutation.mutate,
    isLoggingOut: logoutMutation.isPending,
  };
}
