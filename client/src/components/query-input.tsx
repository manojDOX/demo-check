import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Sparkles, Send, Loader2, History, X, Mic, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";
import { apiRequest } from "@/lib/queryClient";

interface QueryInputProps {
  onSubmit: (query: string) => void;
  isLoading?: boolean;
  placeholder?: string;
  suggestions?: string[];
  recentQueries?: string[];
}

const defaultSuggestions = [
  "What was total online sales last month?",
  "Show me average order value by client",
  "Which customers haven't purchased in 60 days?",
  "What's the recurrence rate this quarter?",
  "Compare new vs returning customer orders",
];

function isVoiceSupported(): boolean {
  if (typeof navigator === "undefined" || !navigator.mediaDevices) {
    return false;
  }
  if (typeof MediaRecorder === "undefined") {
    return false;
  }
  try {
    return MediaRecorder.isTypeSupported("audio/webm") || 
           MediaRecorder.isTypeSupported("audio/mp4") ||
           MediaRecorder.isTypeSupported("audio/ogg");
  } catch {
    return false;
  }
}

function getSupportedMimeType(): string | null {
  const types = ["audio/webm", "audio/mp4", "audio/ogg"];
  for (const type of types) {
    if (MediaRecorder.isTypeSupported(type)) {
      return type;
    }
  }
  return null;
}

export function QueryInput({
  onSubmit,
  isLoading = false,
  placeholder = "Ask anything about your data...",
  suggestions = defaultSuggestions,
  recentQueries = [],
}: QueryInputProps) {
  const [query, setQuery] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [voiceSupported] = useState(isVoiceSupported);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const { toast } = useToast();

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
    }
  }, [query]);

  const handleSubmit = () => {
    if (!query.trim() || isLoading || isRecording) return;
    onSubmit(query.trim());
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    setQuery(suggestion);
    setShowSuggestions(false);
    textareaRef.current?.focus();
  };

  const startRecording = async () => {
    const mimeType = getSupportedMimeType();
    if (!mimeType) {
      toast({
        title: "Voice not supported",
        description: "Your browser doesn't support audio recording.",
        variant: "destructive",
      });
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      
      audioChunksRef.current = [];
      
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onerror = (event) => {
        console.error("MediaRecorder error:", event);
        stream.getTracks().forEach(track => track.stop());
        setIsRecording(false);
        toast({
          title: "Recording error",
          description: "An error occurred while recording. Please try again.",
          variant: "destructive",
        });
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach(track => track.stop());
        
        if (audioChunksRef.current.length === 0) {
          return;
        }

        setIsTranscribing(true);
        try {
          const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });
          const reader = new FileReader();
          
          reader.onerror = () => {
            toast({
              title: "Audio processing failed",
              description: "Could not process the audio recording. Please try again.",
              variant: "destructive",
            });
            setIsTranscribing(false);
          };
          
          reader.onloadend = async () => {
            try {
              const base64Audio = (reader.result as string).split(",")[1];
              
              const response = await apiRequest("POST", "/api/transcribe", {
                audio: base64Audio,
              });
              
              const data = await response.json();
              
              if (data.transcript) {
                setQuery(prev => prev ? `${prev} ${data.transcript}` : data.transcript);
                textareaRef.current?.focus();
              }
            } catch (error) {
              console.error("Transcription error:", error);
              toast({
                title: "Transcription failed",
                description: "Could not convert speech to text. Please try again.",
                variant: "destructive",
              });
            } finally {
              setIsTranscribing(false);
            }
          };
          
          reader.readAsDataURL(audioBlob);
        } catch (error) {
          console.error("Error processing audio:", error);
          toast({
            title: "Audio processing failed",
            description: "Could not process the audio recording. Please try again.",
            variant: "destructive",
          });
          setIsTranscribing(false);
        }
      };

      mediaRecorderRef.current = mediaRecorder;
      mediaRecorder.start();
      setIsRecording(true);
    } catch (error) {
      console.error("Error accessing microphone:", error);
      toast({
        title: "Microphone access denied",
        description: "Please allow microphone access to use voice input.",
        variant: "destructive",
      });
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const handleVoiceClick = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  const isInputDisabled = isLoading || isTranscribing || isRecording;

  return (
    <div className="w-full space-y-4">
      <Card className="relative overflow-hidden border-2 border-transparent focus-within:border-primary/50 transition-colors">
        <div className="flex items-start gap-3 p-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-accent">
            <Sparkles className="h-5 w-5 text-white" />
          </div>
          <div className="flex-1 min-w-0">
            <textarea
              ref={textareaRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={() => setShowSuggestions(true)}
              placeholder={isRecording ? "Listening..." : placeholder}
              className="w-full resize-none border-0 bg-transparent text-base focus:outline-none focus:ring-0 placeholder:text-muted-foreground/60"
              rows={1}
              disabled={isInputDisabled}
              data-testid="input-query"
            />
          </div>
          <div className="flex items-center gap-2">
            {voiceSupported && (
              <Button
                variant={isRecording ? "destructive" : "ghost"}
                size="icon"
                onClick={handleVoiceClick}
                disabled={isLoading || isTranscribing}
                className={cn(
                  "transition-all",
                  isRecording && "animate-pulse"
                )}
                data-testid="button-voice"
                title={isRecording ? "Stop recording" : "Start voice input"}
              >
                {isTranscribing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : isRecording ? (
                  <Square className="h-4 w-4" />
                ) : (
                  <Mic className="h-4 w-4" />
                )}
              </Button>
            )}
            {query && !isRecording && (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setQuery("")}
                disabled={isLoading}
                data-testid="button-clear-query"
              >
                <X className="h-4 w-4" />
              </Button>
            )}
            <Button
              onClick={handleSubmit}
              disabled={!query.trim() || isLoading || isRecording}
              className="gap-2"
              data-testid="button-submit-query"
            >
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              Ask
            </Button>
          </div>
        </div>

        {isRecording && (
          <div className="border-t border-border bg-destructive/10 px-4 py-2">
            <div className="flex items-center gap-2 text-sm text-destructive">
              <div className="h-2 w-2 rounded-full bg-destructive animate-pulse" />
              Recording... Click the stop button when done
            </div>
          </div>
        )}

        {showSuggestions && !query && !isRecording && (
          <div className="border-t border-border">
            <div className="p-4">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-3">
                <Sparkles className="h-3 w-3" />
                Try asking
              </div>
              <div className="flex flex-wrap gap-2">
                {suggestions.slice(0, 4).map((suggestion, index) => (
                  <button
                    key={index}
                    onClick={() => handleSuggestionClick(suggestion)}
                    className="text-left px-3 py-1.5 text-sm rounded-full bg-muted hover-elevate text-foreground transition-colors"
                    data-testid={`suggestion-${index}`}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </Card>

      {recentQueries.length > 0 && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <History className="h-3.5 w-3.5" />
          <span>Recent:</span>
          <div className="flex gap-2 overflow-x-auto custom-scrollbar">
            {recentQueries.slice(0, 3).map((q, i) => (
              <button
                key={i}
                onClick={() => handleSuggestionClick(q)}
                className="shrink-0 px-2 py-1 rounded-md bg-muted/50 hover-elevate text-xs transition-colors truncate max-w-[200px]"
                data-testid={`recent-query-${i}`}
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
