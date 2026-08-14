import { useEffect, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { QueryInput } from "@/components/query-input";
import { QueryResult } from "@/components/query-result";
import { ClientSelector } from "@/components/client-selector";
import { Skeleton } from "@/components/ui/skeleton";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { useChatStream, normalizeChatRows, type ChatRowsPayload } from "@/hooks/use-chat-stream";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  MessageSquare,
  Sparkles,
  History,
  Database,
  AlertCircle,
  ChevronDown,
  X,
  RefreshCw,
  Loader2,
  Plus,
} from "lucide-react";
import type { BigQueryConnection } from "@shared/schema";

interface ChatSessionSummary {
  id: string;
  userId: string;
  clientId: number | null;
  connectionId: number | null;
  tokenId: string | null;
  name: string | null;
  createdAt: string;
  updatedAt: string;
}

interface ChatMessageRecord {
  id: string;
  sessionId: string;
  role: "user" | "assistant";
  content: string;
  sql: string | null;
  confidence: number | null;
  tablesUsed: string[] | null;
  rows: unknown;
  createdAt: string;
  updatedAt: string;
}

interface ConversationTurn {
  id: string;
  question: string;
  summary: string;
  sql: string | null;
  rows: ChatRowsPayload | null;
  confidence: number | null;
  tablesUsed: string[];
}

type VisualizationType = "bar" | "line" | "pie" | "table";

// The SSE `rows` event's `viz.charts[].type` vocabulary is richer than the four chart
// types query-result.tsx's toggle currently renders (bar/line/pie/table) — map the extras
// onto the closest supported visual rather than redesigning the chart component.
function mapChartType(rows: ChatRowsPayload | null): VisualizationType {
  const chart = rows?.viz.charts?.[0];
  if (!chart) return "table";
  switch (chart.type) {
    case "line":
      return "line";
    case "pie":
    case "donut":
      return "pie";
    default:
      return "bar";
  }
}

export default function QueryPage() {
  const [location] = useLocation();
  const [selectedClientId, setSelectedClientId] = useState<number | null>(null);
  const [selectedConnectionId, setSelectedConnectionId] = useState<number | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentQuestion, setCurrentQuestion] = useState("");
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);

  const urlParams = new URLSearchParams(location.split("?")[1] || "");
  const initialQuery = urlParams.get("q") || "";

  const chat = useChatStream();

  const { data: connections, isLoading: isLoadingConnections } = useQuery<BigQueryConnection[]>({
    queryKey: ["/api/connections"],
  });

  const { data: sessions, isLoading: isLoadingSessions } = useQuery<ChatSessionSummary[]>({
    queryKey: ["/api/chat/sessions"],
  });

  // Auto-select first connection (prefer active) when connections load
  useEffect(() => {
    if (connections && connections.length > 0 && !selectedConnectionId) {
      const activeConnection = connections.find((c) => c.isActive);
      const fallbackConnection = connections[0];
      setSelectedConnectionId((activeConnection || fallbackConnection).id);
    }
  }, [connections, selectedConnectionId]);

  // Track the session id as soon as the backend assigns/confirms one (the "session" SSE
  // event, which arrives before "done") so follow-up questions in this turn stay in the
  // same session even while the stream is still in flight.
  useEffect(() => {
    if (chat.sessionId) setSessionId(chat.sessionId);
  }, [chat.sessionId]);

  // When a turn finishes cleanly, fold it into the static turn list and reset the
  // streaming hook for the next question. On error, leave the (possibly partial) state
  // in place so the error card + any partial SQL/text/rows stay visible for the user to
  // inspect or retry.
  useEffect(() => {
    if (!chat.done || chat.error) return;
    setTurns((prev) => [
      ...prev,
      {
        id: `${chat.sessionId ?? sessionId ?? "session"}-${prev.length}-${Date.now()}`,
        question: currentQuestion,
        summary: chat.text,
        sql: chat.sql,
        rows: chat.rows,
        confidence: chat.confidence,
        tablesUsed: chat.tablesUsed,
      },
    ]);
    queryClient.invalidateQueries({ queryKey: ["/api/chat/sessions"] });
    setCurrentQuestion("");
    chat.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chat.done]);

  // Defer initial ?q= query until connections are loaded and one is selected
  const [hasRunInitialQuery, setHasRunInitialQuery] = useState(false);
  useEffect(() => {
    if (initialQuery && !hasRunInitialQuery && !isLoadingConnections) {
      if (connections && connections.length > 0 && !selectedConnectionId) {
        return; // wait for auto-selection
      }
      handleAsk(initialQuery);
      setHasRunInitialQuery(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery, hasRunInitialQuery, isLoadingConnections, connections, selectedConnectionId]);

  const handleAsk = (question: string) => {
    setCurrentQuestion(question);
    chat.send(question, {
      sessionId,
      clientId: selectedClientId,
      connectionId: selectedConnectionId,
    });
  };

  const handleNewChat = () => {
    chat.reset();
    setSessionId(null);
    setTurns([]);
    setCurrentQuestion("");
  };

  const handleSelectSession = async (session: ChatSessionSummary) => {
    if (chat.isStreaming) return;
    chat.reset();
    setSessionId(session.id);
    setCurrentQuestion("");
    setIsLoadingMessages(true);
    try {
      const res = await apiRequest("GET", `/api/chat/sessions/${session.id}/messages`);
      const messages: ChatMessageRecord[] = await res.json();
      const loaded: ConversationTurn[] = [];
      for (let i = 0; i < messages.length; i++) {
        const message = messages[i];
        if (message.role !== "user") continue;
        const next = messages[i + 1];
        if (next && next.role === "assistant") {
          loaded.push({
            id: next.id,
            question: message.content,
            summary: next.content,
            sql: next.sql ?? null,
            rows: normalizeChatRows(next.rows),
            confidence: next.confidence ?? null,
            tablesUsed: next.tablesUsed ?? [],
          });
          i++;
        } else {
          loaded.push({
            id: message.id,
            question: message.content,
            summary: "",
            sql: null,
            rows: null,
            confidence: null,
            tablesUsed: [],
          });
        }
      }
      setTurns(loaded);
    } finally {
      setIsLoadingMessages(false);
    }
  };

  const deleteSessionMutation = useMutation({
    mutationFn: async (id: string) => {
      await apiRequest("DELETE", `/api/chat/sessions/${id}`);
    },
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ["/api/chat/sessions"] });
      if (sessionId === id) handleNewChat();
    },
  });

  const recentQueries = [...turns].reverse().map((t) => t.question).slice(0, 5);
  const orderedTurns = [...turns].reverse();

  const hasLiveContent = Boolean(chat.sql || chat.rows || chat.text);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <MessageSquare className="h-6 w-6 text-primary" />
            Ask Your Data
          </h1>
          <p className="text-muted-foreground mt-1">
            Query your retail data using natural language
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={handleNewChat}
            disabled={chat.isStreaming}
            data-testid="button-new-chat"
          >
            <Plus className="h-4 w-4" />
            New Chat
          </Button>
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-muted-foreground" />
            <Select
              value={selectedConnectionId?.toString() || ""}
              onValueChange={(value) => setSelectedConnectionId(value ? parseInt(value) : null)}
            >
              <SelectTrigger className="w-[200px]" data-testid="select-connection">
                <SelectValue placeholder="Select connection" />
              </SelectTrigger>
              <SelectContent>
                {connections?.map((conn) => (
                  <SelectItem
                    key={conn.id}
                    value={conn.id.toString()}
                    data-testid={`connection-option-${conn.id}`}
                  >
                    <div className="flex items-center gap-2">
                      <span className={`h-2 w-2 rounded-full ${conn.isActive ? "bg-green-500" : "bg-muted"}`} />
                      {conn.name}
                    </div>
                  </SelectItem>
                ))}
                {(!connections || connections.length === 0) && (
                  <div className="px-2 py-1.5 text-sm text-muted-foreground">
                    No connections available
                  </div>
                )}
              </SelectContent>
            </Select>
          </div>
          <ClientSelector
            selectedClientId={selectedClientId}
            onClientChange={setSelectedClientId}
          />
        </div>
      </div>

      <QueryInput
        onSubmit={handleAsk}
        isLoading={chat.isStreaming || isLoadingMessages}
        recentQueries={recentQueries}
      />

      {isLoadingMessages && (
        <Card>
          <CardContent className="pt-6 space-y-3">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-1/3" />
          </CardContent>
        </Card>
      )}

      {chat.isStreaming && !hasLiveContent && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
                <Sparkles className="h-5 w-5 text-primary animate-pulse" />
              </div>
              <div className="space-y-2 flex-1">
                <p className="text-sm font-medium text-muted-foreground">
                  {chat.status || "Thinking…"}
                </p>
                <Skeleton className="h-3 w-32" />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-64 w-full rounded-lg" />
            </div>
          </CardContent>
        </Card>
      )}

      {hasLiveContent && (
        <div className="space-y-3">
          {chat.status && chat.isStreaming && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground px-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              {chat.status}
            </div>
          )}
          <QueryResult
            // QueryResult's chart-type toggle only reads `visualizationType` as its
            // *initial* state (see query-result.tsx's `useState(initialType)`) — remount
            // once `rows` (and therefore the real chart type) becomes available, since
            // `sql` always arrives before `rows` and we don't want to get stuck on the
            // "table" fallback used before we know the chart type.
            key={chat.rows ? "live-with-rows" : "live-pending"}
            query={currentQuestion}
            summary={chat.text || "…"}
            data={chat.rows?.data ?? []}
            sql={chat.sql ?? undefined}
            visualizationType={mapChartType(chat.rows)}
            isStreaming={chat.isStreaming}
          />
        </div>
      )}

      {chat.error && (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardContent className="pt-5 pb-5">
            <div className="flex items-start gap-3">
              <div className="h-10 w-10 rounded-full bg-destructive/10 flex items-center justify-center shrink-0 mt-0.5">
                <AlertCircle className="h-5 w-5 text-destructive" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-medium text-destructive" data-testid="error-title">
                  Something went wrong
                </p>
                <p className="text-sm text-muted-foreground mt-0.5" data-testid="error-detail">
                  {chat.error}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="shrink-0 gap-1.5"
                onClick={() => handleAsk(currentQuestion)}
                disabled={chat.isStreaming || !currentQuestion}
                data-testid="button-retry-query"
              >
                {chat.isStreaming ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Retry
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {orderedTurns.map((turn) => (
        <QueryResult
          key={turn.id}
          query={turn.question}
          summary={turn.summary}
          data={turn.rows?.data ?? []}
          sql={turn.sql ?? undefined}
          visualizationType={mapChartType(turn.rows)}
          clientId={selectedClientId}
        />
      ))}

      <Collapsible open={sessionsOpen} onOpenChange={setSessionsOpen}>
        <Card>
          <CollapsibleTrigger asChild>
            <CardHeader className="cursor-pointer hover-elevate rounded-t-lg">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <History className="h-5 w-5 text-muted-foreground" />
                  <CardTitle className="text-base">Chat Sessions</CardTitle>
                  {sessions && sessions.length > 0 && (
                    <Badge variant="secondary" className="ml-2">{sessions.length}</Badge>
                  )}
                </div>
                <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${sessionsOpen ? "rotate-180" : ""}`} />
              </div>
            </CardHeader>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <CardContent>
              {isLoadingSessions ? (
                <div className="space-y-3">
                  {[...Array(3)].map((_, i) => (
                    <Skeleton key={i} className="h-16 w-full" />
                  ))}
                </div>
              ) : !sessions || sessions.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-center">
                  <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center mb-3">
                    <History className="h-6 w-6 text-muted-foreground" />
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Your chat sessions will appear here
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {sessions.map((session) => (
                    <div
                      key={session.id}
                      className={`flex items-center gap-2 p-3 rounded-lg hover-elevate transition-colors group ${
                        session.id === sessionId ? "bg-primary/10" : "bg-muted/50"
                      }`}
                    >
                      <button
                        onClick={() => handleSelectSession(session)}
                        className="flex-1 text-left min-w-0"
                        data-testid={`session-${session.id}`}
                      >
                        <p className="text-sm font-medium truncate">
                          {session.name || "Untitled conversation"}
                        </p>
                        <p className="text-xs text-muted-foreground mt-1">
                          {new Date(session.updatedAt).toLocaleString()}
                        </p>
                      </button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteSessionMutation.mutate(session.id);
                        }}
                        disabled={deleteSessionMutation.isPending}
                        data-testid={`delete-session-${session.id}`}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>
    </div>
  );
}
