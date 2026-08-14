import { useCallback, useRef, useState } from "react";

/**
 * Client-side (camelCase) shape for the SSE "rows" event. The wire event from
 * POST /api/chat/stream is snake_case (see server_py/app/modules/chat_bot/sql_agent.py
 * and service.py — those events are raw dicts passed straight to json.dumps, NOT run
 * through the app's normal to_camel serializer). We normalize to camelCase here so the
 * rest of the frontend never has to think about the wire format, and so this shape lines
 * up with the camelCase `rows` field already returned by GET /api/chat/sessions/{id}/messages.
 */
export interface ChatChartConfig {
  type: string;
  title?: string;
  xField?: string;
  yField?: string;
  xLabel?: string;
  yLabel?: string;
  [key: string]: unknown;
}

export interface ChatRowsPayload {
  columns: string[];
  data: Array<Record<string, unknown>>;
  totalRows: number;
  truncated: boolean;
  viz: {
    showTable: boolean;
    charts: ChatChartConfig[];
  };
}

export interface SendChatOptions {
  sessionId?: string | null;
  clientId?: number | null;
  connectionId?: number | null;
}

// Raw (snake_case) event shapes exactly as emitted by the SSE endpoint.
type RawRowsEvent = {
  type: "rows";
  columns: string[];
  data: Array<Record<string, unknown>>;
  total_rows: number;
  truncated: boolean;
  viz: { show_table: boolean; charts: Array<Record<string, unknown>> };
};

type RawSseEvent =
  | { type: "session"; session_id: string; name: string | null }
  | { type: "status"; label: string }
  | { type: "sql"; content: string; tables_used: string[] }
  | RawRowsEvent
  | { type: "text"; content: string }
  | { type: "error"; content: string }
  | { type: "done"; confidence: number; tables_used: string[]; session_id: string };

function normalizeChart(raw: Record<string, unknown>): ChatChartConfig {
  const { x_field, y_field, x_label, y_label, ...rest } = raw as Record<string, unknown>;
  return {
    ...rest,
    type: String(raw.type ?? "bar"),
    xField: typeof x_field === "string" ? x_field : undefined,
    yField: typeof y_field === "string" ? y_field : undefined,
    xLabel: typeof x_label === "string" ? x_label : undefined,
    yLabel: typeof y_label === "string" ? y_label : undefined,
  };
}

function normalizeRows(evt: RawRowsEvent): ChatRowsPayload {
  return {
    columns: evt.columns ?? [],
    data: evt.data ?? [],
    totalRows: evt.total_rows ?? 0,
    truncated: Boolean(evt.truncated),
    viz: {
      showTable: Boolean(evt.viz?.show_table),
      charts: (evt.viz?.charts ?? []).map(normalizeChart),
    },
  };
}

/**
 * GET /api/chat/sessions/{id}/messages returns ChatMessage rows via to_camel(), but
 * to_camel() only renames top-level SQLAlchemy column names — it does NOT recurse into
 * JSON column *contents*. The `rows` column is a JSON blob that was written verbatim from
 * the SSE "rows" event (see service.py's `_persist_exchange`/`final_rows_payload`), so its
 * nested keys are still snake_case (`total_rows`, `viz.show_table`, `charts[].x_field`,
 * etc.) exactly like the live SSE event — NOT camelCase. Use this to normalize a stored
 * message's `rows` field the same way we normalize the live SSE event, so both paths
 * produce the same ChatRowsPayload shape for rendering.
 */
export function normalizeChatRows(raw: unknown): ChatRowsPayload | null {
  if (!raw || typeof raw !== "object") return null;
  return normalizeRows({ type: "rows", ...(raw as Record<string, unknown>) } as RawRowsEvent);
}

export interface UseChatStreamResult {
  send: (message: string, options?: SendChatOptions) => void;
  stop: () => void;
  reset: () => void;
  status: string | null;
  sql: string | null;
  rows: ChatRowsPayload | null;
  text: string;
  sessionId: string | null;
  isStreaming: boolean;
  error: string | null;
  done: boolean;
  confidence: number | null;
  tablesUsed: string[];
}

/**
 * Wraps the SSE-over-fetch POST to /api/chat/stream (EventSource can't do POST bodies
 * with credentials, so we parse the `data: <json>\n\n` frames off a fetch() ReadableStream
 * ourselves). One `send()` call drives one streaming turn; state resets at the start of
 * each new send() and accumulates (sql/text/rows) as events arrive.
 */
export function useChatStream(): UseChatStreamResult {
  const [status, setStatus] = useState<string | null>(null);
  const [sql, setSql] = useState<string | null>(null);
  const [rows, setRows] = useState<ChatRowsPayload | null>(null);
  const [text, setText] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [confidence, setConfidence] = useState<number | null>(null);
  const [tablesUsed, setTablesUsed] = useState<string[]>([]);

  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus(null);
    setSql(null);
    setRows(null);
    setText("");
    setSessionId(null);
    setIsStreaming(false);
    setError(null);
    setDone(false);
    setConfidence(null);
    setTablesUsed([]);
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
  }, []);

  const send = useCallback((message: string, options: SendChatOptions = {}) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setStatus("Thinking…");
    setSql(null);
    setRows(null);
    setText("");
    setError(null);
    setDone(false);
    setConfidence(null);
    setTablesUsed([]);
    setIsStreaming(true);

    (async () => {
      try {
        const res = await fetch("/api/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            sessionId: options.sessionId ?? undefined,
            message,
            clientId: options.clientId ?? undefined,
            connectionId: options.connectionId ?? undefined,
          }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          let msg = res.statusText || "Failed to start chat stream.";
          try {
            const parsed = await res.json();
            msg = parsed.error || parsed.message || msg;
          } catch {
            // response wasn't JSON — keep statusText
          }
          throw new Error(msg);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { value, done: readerDone } = await reader.read();
          if (readerDone) break;
          buffer += decoder.decode(value, { stream: true });

          let sepIndex: number;
          while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
            const rawFrame = buffer.slice(0, sepIndex);
            buffer = buffer.slice(sepIndex + 2);

            const dataLines = rawFrame
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trimStart());
            if (dataLines.length === 0) continue;

            let event: RawSseEvent;
            try {
              event = JSON.parse(dataLines.join("\n"));
            } catch {
              continue;
            }

            switch (event.type) {
              case "session":
                setSessionId(event.session_id);
                break;
              case "status":
                setStatus(event.label);
                break;
              case "sql":
                setSql(event.content);
                break;
              case "rows":
                setRows(normalizeRows(event));
                break;
              case "text":
                setText((prev) => prev + event.content);
                break;
              case "error":
                setError(event.content);
                break;
              case "done":
                setConfidence(event.confidence);
                setTablesUsed(event.tables_used ?? []);
                setSessionId(event.session_id);
                setStatus(null);
                setDone(true);
                break;
            }
          }
        }
      } catch (err) {
        if ((err as { name?: string })?.name !== "AbortError") {
          setError(err instanceof Error ? err.message : "Something went wrong while streaming the response.");
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    })();
  }, []);

  return {
    send,
    stop,
    reset,
    status,
    sql,
    rows,
    text,
    sessionId,
    isStreaming,
    error,
    done,
    confidence,
    tablesUsed,
  };
}
