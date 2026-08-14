import { QueryClient, QueryFunction } from "@tanstack/react-query";

export class ApiError extends Error {
  status: number;
  errorType: string | undefined;

  constructor(message: string, status: number, errorType?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errorType = errorType;
  }
}

async function throwIfResNotOk(res: Response) {
  if (!res.ok) {
    const text = await res.text();
    let message = res.statusText;
    let errorType: string | undefined;
    try {
      const parsed = JSON.parse(text);
      message = parsed.error || parsed.message || text || res.statusText;
      errorType = parsed.errorType;
    } catch {
      message = text || res.statusText;
    }
    throw new ApiError(message, res.status, errorType);
  }
}

export async function apiRequest(
  method: string,
  url: string,
  data?: unknown | undefined,
): Promise<Response> {
  const res = await fetch(url, {
    method,
    headers: data ? { "Content-Type": "application/json" } : {},
    body: data ? JSON.stringify(data) : undefined,
    credentials: "include",
  });

  await throwIfResNotOk(res);
  return res;
}

type UnauthorizedBehavior = "returnNull" | "throw";

function buildUrl(queryKey: readonly unknown[]): string {
  const [path, ...params] = queryKey;
  let url = String(path);
  
  const queryParams: string[] = [];
  for (const param of params) {
    if (param === null || param === undefined) continue;
    if (typeof param === "object") {
      for (const [key, value] of Object.entries(param as Record<string, unknown>)) {
        if (value !== null && value !== undefined) {
          queryParams.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
        }
      }
    } else {
      if (!url.includes("?")) {
        url += `/${String(param)}`;
      }
    }
  }
  
  if (queryParams.length > 0) {
    url += (url.includes("?") ? "&" : "?") + queryParams.join("&");
  }
  
  return url;
}

export const getQueryFn: <T>(options: {
  on401: UnauthorizedBehavior;
}) => QueryFunction<T> =
  ({ on401: unauthorizedBehavior }) =>
  async ({ queryKey }) => {
    const url = buildUrl(queryKey);
    const res = await fetch(url, {
      credentials: "include",
    });

    if (unauthorizedBehavior === "returnNull" && res.status === 401) {
      return null;
    }

    await throwIfResNotOk(res);
    return await res.json();
  };

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      queryFn: getQueryFn({ on401: "throw" }),
      refetchInterval: false,
      refetchOnWindowFocus: false,
      staleTime: Infinity,
      retry: false,
    },
    mutations: {
      retry: false,
    },
  },
});
