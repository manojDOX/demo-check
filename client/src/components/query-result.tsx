import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { 
  Copy, 
  Download, 
  BarChart3, 
  LineChartIcon, 
  PieChartIcon,
  Table,
  Sparkles,
  Clock,
  Code,
  Volume2,
  VolumeX,
  Loader2,
  ChevronDown,
  Bookmark,
  BookmarkCheck,
  X,
  FileText,
  Users,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import html2canvas from "html2canvas";
import jsPDF from "jspdf";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { useState, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useToast } from "@/hooks/use-toast";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { Send, AlertTriangle, Filter } from "lucide-react";
import { Progress } from "@/components/ui/progress";

type VisualizationType = "bar" | "line" | "pie" | "table";

interface QueryResultProps {
  query: string;
  summary: string;
  data: Array<Record<string, unknown>>;
  sql?: string;
  executionTime?: number;
  visualizationType?: VisualizationType;
  isStreaming?: boolean;
  queryId?: number;
  isSaved?: boolean;
  clientId?: number | null;
  onClose?: () => void;
  isRecommendation?: boolean;
  recommendation?: string;
  onDrillDown?: () => void;
  isDrillDownMode?: boolean;
}

const CHART_COLORS = [
  "hsl(217, 91%, 60%)",
  "hsl(199, 89%, 48%)",
  "hsl(142, 71%, 45%)",
  "hsl(38, 92%, 50%)",
  "hsl(280, 68%, 60%)",
];

// Renders the chatbot's plain-text answer with minimal structure: a blank line starts a new
// paragraph, a line starting "- " becomes a bullet row, and "**bold**" spans become <strong>.
// No markdown headers/numbered lists — the answer-generation prompt (prompts.py) is instructed
// to stick to exactly this subset, so this renderer only needs to handle exactly this subset.
function FormattedAnswerText({ text }: { text: string }) {
  const renderInline = (line: string, key: string | number) => {
    const parts = line.split(/(\*\*.*?\*\*)/g);
    return (
      <span key={key}>
        {parts.map((part, j) =>
          part.startsWith("**") && part.endsWith("**") ? (
            <strong key={j}>{part.slice(2, -2)}</strong>
          ) : (
            part
          )
        )}
      </span>
    );
  };

  return (
    <>
      {text.split("\n").map((line, i) => {
        if (line.trim() === "") return <div key={i} className="h-2" />;
        if (line.startsWith("- ")) {
          return (
            <div key={i} className="flex gap-2 my-1">
              <span className="text-primary mt-0.5">-</span>
              {renderInline(line.replace("- ", ""), `${i}-content`)}
            </div>
          );
        }
        return <p key={i}>{renderInline(line, `${i}-content`)}</p>;
      })}
    </>
  );
}

export function QueryResult({
  query,
  summary,
  data,
  sql,
  executionTime,
  visualizationType: initialType = "bar",
  isStreaming = false,
  queryId,
  isSaved: initialSaved = false,
  clientId,
  onClose,
  isRecommendation = false,
  recommendation,
  onDrillDown,
  isDrillDownMode = false,
}: QueryResultProps) {
  const [vizType, setVizType] = useState<VisualizationType>(initialType);
  const [isSaved, setIsSaved] = useState(initialSaved);
  const [isSaving, setIsSaving] = useState(false);
  const [showSql, setShowSql] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isLoadingAudio, setIsLoadingAudio] = useState(false);
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);
  const [showSegmentDialog, setShowSegmentDialog] = useState(false);
  const [segmentName, setSegmentName] = useState("");
  const [isCreatingSegment, setIsCreatingSegment] = useState(false);
  const [isSendingToGhl, setIsSendingToGhl] = useState(false);
  const [showGhlDialog, setShowGhlDialog] = useState(false);
  const [ghlResult, setGhlResult] = useState<{ total: number; created: number; updated: number; failed: number; errors: string[]; duplicatesRemoved?: number } | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const { toast } = useToast();

  const { data: ghlSettings } = useQuery<{ isConfigured: boolean }>({
    queryKey: ["/api/ghl/settings"],
  });

  // Check if results look like customer data (contains customer_id or email)
  // Look at all columns across all rows for better detection
  const isCustomerData = (() => {
    if (data.length === 0) return false;
    
    // Collect all unique column names from the dataset
    const allColumns = new Set<string>();
    data.forEach(row => {
      if (row && typeof row === 'object') {
        Object.keys(row).forEach(key => allColumns.add(key.toLowerCase()));
      }
    });
    
    // Check for exact customer identifier field names
    const customerIdentifiers = ['customer_id', 'customerid', 'email', 'user_id', 'userid', 'contact_id', 'contactid'];
    return customerIdentifiers.some(id => allColumns.has(id));
  })();

  const handleCreateSegment = async () => {
    if (!segmentName.trim()) {
      toast({
        title: "Nombre requerido",
        description: "Por favor ingresa un nombre para el segmento",
        variant: "destructive",
      });
      return;
    }

    setIsCreatingSegment(true);
    try {
      await apiRequest("POST", "/api/segments/from-query", {
        name: segmentName.trim(),
        description: `Segmento creado desde consulta: "${query}"`,
        sql: sql,
        memberData: data,
        contactCount: data.length,
        clientId: clientId || null,
      });

      toast({
        title: "Segmento creado",
        description: `El segmento "${segmentName}" ha sido creado exitosamente`,
      });

      queryClient.invalidateQueries({ queryKey: ["/api/segments"] });
      setShowSegmentDialog(false);
      setSegmentName("");
    } catch (error: any) {
      toast({
        title: "Error",
        description: error.message || "No se pudo crear el segmento",
        variant: "destructive",
      });
    } finally {
      setIsCreatingSegment(false);
    }
  };

  const handleSendToGhl = async () => {
    if (!ghlSettings?.isConfigured) {
      toast({
        title: "GoHighLevel not configured",
        description: "Please add your API Key and Location ID in Settings first.",
        variant: "destructive",
      });
      return;
    }

    setIsSendingToGhl(true);
    setGhlResult(null);
    try {
      const allColumns = new Set<string>();
      data.forEach(row => {
        if (row && typeof row === 'object') {
          Object.keys(row).forEach(key => allColumns.add(key.toLowerCase()));
        }
      });
      const colArray = Array.from(allColumns);

      const nameCol = colArray.find(c => ['name', 'customer_name', 'contact_name', 'full_name', 'nombre'].includes(c));
      const firstNameCol = colArray.find(c => ['first_name', 'firstname', 'primer_nombre'].includes(c));
      const lastNameCol = colArray.find(c => ['last_name', 'lastname', 'apellido'].includes(c));
      const emailCol = colArray.find(c => ['email', 'correo', 'email_address', 'customer_email'].includes(c));
      const phoneCol = colArray.find(c => ['phone', 'telephone', 'phone_number', 'telefono', 'mobile', 'celular', 'tel'].includes(c));

      const rawContacts = data.map(row => {
        const contact: Record<string, string> = {};
        const getVal = (col: string | undefined) => {
          if (!col) return undefined;
          const key = Object.keys(row).find(k => k.toLowerCase() === col);
          if (!key) return undefined;
          const val = row[key];
          if (val && typeof val === 'object' && 'value' in val) return String((val as any).value || "");
          return val ? String(val) : undefined;
        };

        const name = getVal(nameCol);
        const firstName = getVal(firstNameCol);
        const lastName = getVal(lastNameCol);
        const email = getVal(emailCol);
        const phone = getVal(phoneCol);

        if (name) contact.name = name;
        if (firstName) contact.firstName = firstName;
        if (lastName) contact.lastName = lastName;
        if (email) contact.email = email;
        if (phone) contact.phone = phone;

        return contact;
      }).filter(c => Object.keys(c).length > 0);

      const seen = new Set<string>();
      const contacts = rawContacts.filter(c => {
        const dedupeKey = (c.email || c.phone || "").toLowerCase().trim();
        if (!dedupeKey) return true;
        if (seen.has(dedupeKey)) return false;
        seen.add(dedupeKey);
        return true;
      });

      const duplicatesRemoved = rawContacts.length - contacts.length;

      if (contacts.length === 0) {
        toast({
          title: "No contacts to send",
          description: "Could not map any contact data from the query results.",
          variant: "destructive",
        });
        setIsSendingToGhl(false);
        return;
      }

      const BATCH_SIZE = 500;
      const totalBatches = Math.ceil(contacts.length / BATCH_SIZE);
      const aggregated = { total: contacts.length, created: 0, updated: 0, failed: 0, errors: [] as string[], duplicatesRemoved };

      for (let i = 0; i < totalBatches; i++) {
        const batch = contacts.slice(i * BATCH_SIZE, (i + 1) * BATCH_SIZE);

        if (totalBatches > 1) {
          toast({
            title: `Sending batch ${i + 1} of ${totalBatches}`,
            description: `${batch.length} contacts in this batch...`,
          });
        }

        const response = await apiRequest("POST", "/api/ghl/send-contacts", {
          contacts: batch,
          tags: [],
        });
        const result = await response.json();

        aggregated.created += result.created || 0;
        aggregated.updated += result.updated || 0;
        aggregated.failed += result.failed || 0;
        if (result.errors) {
          aggregated.errors.push(...result.errors);
        }
      }

      setGhlResult(aggregated);
      setShowGhlDialog(true);

      if (aggregated.failed === 0) {
        toast({
          title: "Contacts sent successfully",
          description: `${aggregated.created + aggregated.updated} contacts synced to GoHighLevel${duplicatesRemoved > 0 ? ` (${duplicatesRemoved} duplicates skipped)` : ""}`,
        });
      } else {
        toast({
          title: "Partial sync completed",
          description: `${aggregated.created + aggregated.updated} sent, ${aggregated.failed} failed${duplicatesRemoved > 0 ? `, ${duplicatesRemoved} duplicates skipped` : ""}`,
          variant: "destructive",
        });
      }
    } catch (error: any) {
      toast({
        title: "Error",
        description: error.message || "Failed to send contacts to GoHighLevel",
        variant: "destructive",
      });
    } finally {
      setIsSendingToGhl(false);
    }
  };

  const handleSaveToggle = async () => {
    if (!queryId) {
      toast({
        title: "No se puede guardar",
        description: "Esta consulta no tiene un ID válido. Por favor ejecuta la consulta de nuevo.",
        variant: "destructive",
      });
      return;
    }

    setIsSaving(true);
    try {
      const response = await apiRequest("PATCH", `/api/queries/${queryId}/save`, { isSaved: !isSaved });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || "Error al guardar");
      }
      setIsSaved(!isSaved);
      queryClient.invalidateQueries({ queryKey: ["/api/queries/saved"] });
      toast({
        title: isSaved ? "Gráfica removida del dashboard" : "Gráfica guardada en el dashboard",
      });
    } catch (error) {
      toast({
        title: "Error al guardar",
        description: error instanceof Error ? error.message : "Por favor intenta de nuevo",
        variant: "destructive",
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleCopyData = async () => {
    if (!data || data.length === 0) {
      toast({
        title: "Sin datos",
        description: "No hay datos para copiar",
        variant: "destructive",
      });
      return;
    }

    try {
      const headers = Object.keys(data[0]);
      const rows = data.map(row => 
        headers.map(h => {
          const val = extractValue(row[h]);
          return typeof val === "object" ? JSON.stringify(val) : String(val ?? "");
        }).join("\t")
      );
      const text = [headers.join("\t"), ...rows].join("\n");
      
      await navigator.clipboard.writeText(text);
      toast({
        title: "Datos copiados",
        description: `${data.length} filas copiadas al portapapeles`,
      });
    } catch (error) {
      toast({
        title: "Error",
        description: "No se pudo copiar los datos",
        variant: "destructive",
      });
    }
  };

  const handleDownloadCsv = () => {
    if (!data || data.length === 0) {
      toast({
        title: "Sin datos",
        description: "No hay datos para descargar",
        variant: "destructive",
      });
      return;
    }

    try {
      const headers = Object.keys(data[0]);
      const csvRows = [
        headers.join(","),
        ...data.map(row => 
          headers.map(h => {
            const val = extractValue(row[h]);
            const str = typeof val === "object" ? JSON.stringify(val) : String(val ?? "");
            return str.includes(",") || str.includes('"') || str.includes("\n") 
              ? `"${str.replace(/"/g, '""')}"` 
              : str;
          }).join(",")
        )
      ];
      
      const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `query-result-${new Date().toISOString().slice(0,10)}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      
      toast({
        title: "Descarga iniciada",
        description: `Archivo CSV con ${data.length} filas`,
      });
    } catch (error) {
      toast({
        title: "Error",
        description: "No se pudo descargar el archivo",
        variant: "destructive",
      });
    }
  };

  const handleDownloadPdf = async () => {
    if (!contentRef.current) {
      toast({
        title: "Error",
        description: "No se pudo generar el PDF",
        variant: "destructive",
      });
      return;
    }

    setIsGeneratingPdf(true);
    try {
      const canvas = await html2canvas(contentRef.current, {
        scale: 2,
        useCORS: true,
        backgroundColor: "#ffffff",
        logging: false,
      });
      
      const imgData = canvas.toDataURL("image/png");
      const imgWidth = canvas.width;
      const imgHeight = canvas.height;
      
      const pdfWidth = 210;
      const pdfHeight = (imgHeight * pdfWidth) / imgWidth;
      
      const pdf = new jsPDF({
        orientation: pdfHeight > pdfWidth ? "portrait" : "landscape",
        unit: "mm",
        format: [pdfWidth, Math.max(pdfHeight, 297)],
      });
      
      pdf.addImage(imgData, "PNG", 0, 0, pdfWidth, pdfHeight);
      pdf.save(`query-result-${new Date().toISOString().slice(0,10)}.pdf`);
      
      toast({
        title: "PDF generado",
        description: "El archivo PDF se ha descargado correctamente",
      });
    } catch (error) {
      console.error("Error generating PDF:", error);
      toast({
        title: "Error",
        description: "No se pudo generar el PDF",
        variant: "destructive",
      });
    } finally {
      setIsGeneratingPdf(false);
    }
  };

  // Helper to extract value from BigQuery objects
  const extractValue = (value: unknown): unknown => {
    if (value && typeof value === "object" && "value" in value) {
      return (value as { value: unknown }).value;
    }
    return value;
  };

  // Spanish month names
  const monthNames = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

  // Convert month number to name
  const formatMonthNumber = (value: number | string): string => {
    const num = typeof value === "string" ? parseInt(value, 10) : value;
    if (num >= 1 && num <= 12) {
      return monthNames[num - 1];
    }
    return String(value);
  };

  // Normalize data to handle BigQuery timestamp objects
  const normalizedData = data.map(row => {
    const normalized: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(row)) {
      const extracted = extractValue(value);
      const lowerKey = key.toLowerCase();
      
      // Convert month numbers to names
      if ((lowerKey === "month" || lowerKey === "mes" || lowerKey.includes("month") || lowerKey.includes("mes")) &&
          (typeof extracted === "number" || (typeof extracted === "string" && /^\d{1,2}$/.test(extracted)))) {
        normalized[key] = formatMonthNumber(extracted as number | string);
      }
      // Format dates/timestamps for display
      else if (typeof extracted === "string" && /^\d{4}-\d{2}-\d{2}/.test(extracted)) {
        // Format as readable date (e.g., "Sep 2025" or "2025-09-01")
        const date = new Date(extracted);
        if (!isNaN(date.getTime())) {
          normalized[key] = date.toLocaleDateString("es-ES", { 
            year: "numeric", 
            month: "short" 
          });
        } else {
          normalized[key] = extracted;
        }
      } else {
        normalized[key] = extracted;
      }
    }
    return normalized;
  });

  // Sort data chronologically if it contains date/time fields
  const sortedData = [...normalizedData].sort((a, b) => {
    // Get original data for sorting (before month name conversion)
    const aOriginal = data[normalizedData.indexOf(a)];
    const bOriginal = data[normalizedData.indexOf(b)];
    
    // Try to find year and month fields for sorting
    const findField = (row: Record<string, unknown>, ...names: string[]): unknown => {
      for (const name of names) {
        const key = Object.keys(row).find(k => k.toLowerCase() === name.toLowerCase());
        if (key) return extractValue(row[key]);
      }
      return undefined;
    };
    
    const aYear = Number(findField(aOriginal, "year", "año", "ano")) || 0;
    const bYear = Number(findField(bOriginal, "year", "año", "ano")) || 0;
    const aMonth = Number(findField(aOriginal, "month", "mes")) || 0;
    const bMonth = Number(findField(bOriginal, "month", "mes")) || 0;
    
    // If we have year/month, sort chronologically
    if (aYear || bYear || aMonth || bMonth) {
      if (aYear !== bYear) return aYear - bYear;
      return aMonth - bMonth;
    }
    
    // Try to find date fields
    const aDate = findField(aOriginal, "date", "fecha", "created_at", "timestamp");
    const bDate = findField(bOriginal, "date", "fecha", "created_at", "timestamp");
    
    if (aDate && bDate) {
      return new Date(String(aDate)).getTime() - new Date(String(bDate)).getTime();
    }
    
    return 0;
  });

  // Determine the label key (x-axis) and numeric data keys (y-axis)
  const labelKey = sortedData.length > 0
    ? (Object.keys(sortedData[0]).find(k =>
        k === "name" || k === "label" || k === "month" || k === "date" ||
        k.includes("_name") || k.includes("_id") || k.includes("mes") ||
        k.includes("fecha") || k.includes("period") ||
        k.endsWith("_date") || k.endsWith("_at") || k.includes("date")
      ) || Object.keys(sortedData[0])[0])
    : "name";
  
  // Get numeric keys for chart data (exclude the label key, non-numeric fields, and year/id columns)
  const keys = sortedData.length > 0 
    ? Object.keys(sortedData[0]).filter(k => {
        if (k === labelKey || k === "name" || k === "label") return false;
        
        // Exclude year/ID type columns - these are grouping fields, not metrics
        const lowerKey = k.toLowerCase();
        if (lowerKey === "year" || lowerKey === "año" || lowerKey === "ano" || 
            lowerKey === "id" || lowerKey.endsWith("_id") || lowerKey.endsWith("_year") ||
            lowerKey === "month" || lowerKey === "mes" || lowerKey === "day" || lowerKey === "dia") {
          return false;
        }
        
        // Check if the value is numeric
        const sampleValue = sortedData[0][k];
        const isNumeric = typeof sampleValue === "number" || (typeof sampleValue === "string" && !isNaN(Number(sampleValue)));
        
        // Additional check: if all values are 4-digit numbers (years like 2024, 2025), exclude
        if (isNumeric && sortedData.length > 0) {
          const allYearLike = sortedData.every(row => {
            const val = Number(row[k]);
            return val >= 1900 && val <= 2100 && Number.isInteger(val);
          });
          if (allYearLike) return false;
        }
        
        return isNumeric;
      })
    : [];

  // Format cell value for display
  const formatCellValue = (value: unknown): { display: string; isComplex: boolean; formatted: string } => {
    if (value === null || value === undefined) {
      return { display: "null", isComplex: false, formatted: "null" };
    }
    
    // Handle Date objects or date-like objects with 'value' property
    if (value instanceof Date) {
      const formatted = value.toLocaleString();
      return { display: formatted, isComplex: false, formatted };
    }
    
    // Handle BigQuery timestamp objects (they have a 'value' property)
    if (typeof value === "object" && value !== null && "value" in value) {
      const innerValue = (value as { value: unknown }).value;
      if (typeof innerValue === "string") {
        // Try to parse as date
        const date = new Date(innerValue);
        if (!isNaN(date.getTime())) {
          const formatted = date.toLocaleString();
          return { display: formatted, isComplex: false, formatted };
        }
        return { display: innerValue, isComplex: false, formatted: innerValue };
      }
    }
    
    // Handle arrays
    if (Array.isArray(value)) {
      const formatted = JSON.stringify(value, null, 2);
      const display = value.length > 3 
        ? `[${value.slice(0, 3).map(v => typeof v === 'object' ? '...' : String(v)).join(', ')}... +${value.length - 3}]`
        : JSON.stringify(value);
      return { display, isComplex: value.length > 0, formatted };
    }
    
    // Handle objects (not Date, not array)
    if (typeof value === "object" && value !== null) {
      const formatted = JSON.stringify(value, null, 2);
      const objKeys = Object.keys(value);
      if (objKeys.length <= 2) {
        // Small object - show inline
        const display = objKeys.map(k => `${k}: ${String((value as Record<string, unknown>)[k]).slice(0, 20)}`).join(', ');
        return { display, isComplex: true, formatted };
      }
      // Larger object - show summary
      return { display: `{${objKeys.length} fields}`, isComplex: true, formatted };
    }
    
    // Handle strings that look like dates
    if (typeof value === "string") {
      const isoDatePattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;
      if (isoDatePattern.test(value)) {
        const date = new Date(value);
        if (!isNaN(date.getTime())) {
          return { display: date.toLocaleString(), isComplex: false, formatted: date.toLocaleString() };
        }
      }
    }
    
    // Primitive values
    return { display: String(value), isComplex: false, formatted: String(value) };
  };

  // Cell renderer component
  const CellValue = ({ value }: { value: unknown }) => {
    const { display, isComplex, formatted } = formatCellValue(value);
    
    if (!isComplex) {
      return <span className="text-foreground">{display}</span>;
    }
    
    return (
      <Popover>
        <PopoverTrigger asChild>
          <button className="flex items-center gap-1 text-left hover:text-primary transition-colors">
            <span className="text-muted-foreground">{display}</span>
            <ChevronDown className="h-3 w-3 text-muted-foreground" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-80 max-h-64 overflow-auto">
          <pre className="text-xs font-mono whitespace-pre-wrap break-all">
            {formatted}
          </pre>
        </PopoverContent>
      </Popover>
    );
  };

  const handleSpeak = async () => {
    if (isPlaying && audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      setIsPlaying(false);
      return;
    }

    setIsLoadingAudio(true);
    try {
      const response = await apiRequest("POST", "/api/speak", {
        text: summary,
        voice: "alloy",
      });

      const data = await response.json();

      if (data.audio) {
        const audioBlob = new Blob(
          [Uint8Array.from(atob(data.audio), c => c.charCodeAt(0))],
          { type: "audio/mp3" }
        );
        const audioUrl = URL.createObjectURL(audioBlob);
        
        if (audioRef.current) {
          audioRef.current.pause();
        }

        const audio = new Audio(audioUrl);
        audioRef.current = audio;

        audio.onended = () => {
          setIsPlaying(false);
          URL.revokeObjectURL(audioUrl);
        };

        audio.onerror = () => {
          setIsPlaying(false);
          URL.revokeObjectURL(audioUrl);
          toast({
            title: "Playback failed",
            description: "Could not play the audio response.",
            variant: "destructive",
          });
        };

        await audio.play();
        setIsPlaying(true);
      }
    } catch (error) {
      console.error("TTS error:", error);
      toast({
        title: "Voice response failed",
        description: "Could not generate audio response. Please try again.",
        variant: "destructive",
      });
    } finally {
      setIsLoadingAudio(false);
    }
  };

  const renderChart = () => {
    if (sortedData.length === 0) {
      return (
        <div className="flex items-center justify-center h-64 text-muted-foreground">
          No data to display
        </div>
      );
    }

    switch (vizType) {
      case "bar":
        return (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={sortedData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis 
                dataKey={labelKey} 
                tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                axisLine={{ stroke: "hsl(var(--border))" }}
              />
              <YAxis 
                tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                axisLine={{ stroke: "hsl(var(--border))" }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "var(--radius)",
                }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
                formatter={(value: number) => [
                  typeof value === "number" ? `$${value.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : value,
                ]}
              />
              <Legend />
              {keys.map((key, index) => (
                <Bar
                  key={key}
                  dataKey={key}
                  fill={CHART_COLORS[index % CHART_COLORS.length]}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        );

      case "line":
        return (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={sortedData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis 
                dataKey={labelKey}
                tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                axisLine={{ stroke: "hsl(var(--border))" }}
              />
              <YAxis 
                tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                axisLine={{ stroke: "hsl(var(--border))" }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "var(--radius)",
                }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
                formatter={(value: number) => [
                  typeof value === "number" ? `$${value.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : value,
                ]}
              />
              <Legend />
              {keys.map((key, index) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={CHART_COLORS[index % CHART_COLORS.length]}
                  strokeWidth={2}
                  dot={{ fill: CHART_COLORS[index % CHART_COLORS.length] }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        );

      case "pie":
        const pieData = sortedData.map((item, index) => ({
          name: String(item[labelKey]),
          value: Number(item[keys[0]] || 0),
          fill: CHART_COLORS[index % CHART_COLORS.length],
        }));
        return (
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}
                outerRadius={100}
                fill="#8884d8"
                dataKey="value"
              >
                {pieData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "var(--radius)",
                }}
              />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        );

      case "table":
        return (
          <div className="overflow-x-auto custom-scrollbar">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  {Object.keys(data[0] || {}).map((header) => (
                    <th
                      key={header}
                      className="px-4 py-3 text-left font-medium text-muted-foreground"
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.map((row, i) => (
                  <tr key={i} className="border-b border-border/50 hover-elevate">
                    {Object.values(row).map((value, j) => (
                      <td key={j} className="px-4 py-3">
                        <CellValue value={value} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
    }
  };

  return (
    <Card className="overflow-hidden" data-testid="query-result" ref={contentRef}>
      <CardHeader className="border-b border-border bg-muted/30 pb-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2">
              <Sparkles className="h-3 w-3" />
              Query
            </div>
            <CardTitle className="text-base font-medium truncate">{query}</CardTitle>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {executionTime && (
              <Badge variant="secondary" className="gap-1">
                <Clock className="h-3 w-3" />
                {executionTime}ms
              </Badge>
            )}
            {isStreaming && (
              <Badge variant="default" className="animate-pulse">
                Analyzing...
              </Badge>
            )}
            {onClose && (
              <Button 
                variant="ghost" 
                size="icon" 
                onClick={onClose}
                className="h-8 w-8"
                data-testid="button-close-result"
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-6">
        <div className="space-y-6">
          <div className="p-4 bg-muted/30 rounded-lg">
            <div className="flex items-center justify-between gap-2 mb-2">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Sparkles className="h-3 w-3 text-primary" />
                AI Summary
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleSpeak}
                disabled={isLoadingAudio || isStreaming}
                className={cn(
                  "gap-2 h-7",
                  isPlaying && "text-primary"
                )}
                data-testid="button-speak"
              >
                {isLoadingAudio ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : isPlaying ? (
                  <VolumeX className="h-3.5 w-3.5" />
                ) : (
                  <Volume2 className="h-3.5 w-3.5" />
                )}
                <span className="text-xs">{isPlaying ? "Stop" : "Listen"}</span>
              </Button>
            </div>
            <div className="text-foreground"><FormattedAnswerText text={summary} /></div>
          </div>

          {isRecommendation && recommendation && (
            <div className="p-6 bg-gradient-to-br from-primary/5 to-primary/10 rounded-lg border border-primary/20" data-testid="recommendation-content">
              <div className="flex items-center gap-2 mb-4">
                <Sparkles className="h-5 w-5 text-primary" />
                <h3 className="font-semibold text-lg text-foreground">Recomendaciones de Marketing</h3>
              </div>
              <div className="prose prose-sm dark:prose-invert max-w-none text-foreground [&_h2]:text-base [&_h2]:font-semibold [&_h2]:mt-4 [&_h2]:mb-2 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1 [&_ul]:my-2 [&_li]:my-0.5 [&_p]:my-2 [&_strong]:text-primary">
                {recommendation.split('\n').map((line, i) => {
                  if (line.startsWith('## ')) return <h2 key={i}>{line.replace('## ', '')}</h2>;
                  if (line.startsWith('### ')) return <h3 key={i}>{line.replace('### ', '')}</h3>;
                  if (line.startsWith('- ')) {
                    const content = line.replace('- ', '');
                    const parts = content.split(/(\*\*.*?\*\*)/g);
                    return (
                      <div key={i} className="flex gap-2 my-1">
                        <span className="text-primary mt-0.5">-</span>
                        <span>{parts.map((part, j) => 
                          part.startsWith('**') && part.endsWith('**') 
                            ? <strong key={j}>{part.slice(2, -2)}</strong> 
                            : part
                        )}</span>
                      </div>
                    );
                  }
                  if (line.trim() === '') return <div key={i} className="h-2" />;
                  const parts = line.split(/(\*\*.*?\*\*)/g);
                  return <p key={i}>{parts.map((part, j) => 
                    part.startsWith('**') && part.endsWith('**') 
                      ? <strong key={j}>{part.slice(2, -2)}</strong> 
                      : part
                  )}</p>;
                })}
              </div>
            </div>
          )}

          {!isRecommendation && (
          <>
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-1 p-1 bg-muted rounded-lg">
              {[
                { type: "bar" as const, icon: BarChart3 },
                { type: "line" as const, icon: LineChartIcon },
                { type: "pie" as const, icon: PieChartIcon },
                { type: "table" as const, icon: Table },
              ].map(({ type, icon: Icon }) => (
                <Button
                  key={type}
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "gap-2",
                    vizType === type && "bg-background shadow-sm"
                  )}
                  onClick={() => setVizType(type)}
                  data-testid={`viz-${type}`}
                >
                  <Icon className="h-4 w-4" />
                  <span className="hidden sm:inline capitalize">{type}</span>
                </Button>
              ))}
            </div>

            <div className="flex items-center gap-2">
              {sql && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowSql(!showSql)}
                  className="gap-2"
                  data-testid="button-show-sql"
                >
                  <Code className="h-4 w-4" />
                  {showSql ? "Hide SQL" : "View SQL"}
                </Button>
              )}
              <Button 
                variant="outline" 
                size="icon" 
                data-testid="button-copy-result"
                onClick={handleCopyData}
                title="Copiar datos"
              >
                <Copy className="h-4 w-4" />
              </Button>
              <Button 
                variant="outline" 
                size="icon" 
                data-testid="button-download-result"
                onClick={handleDownloadCsv}
                title="Descargar CSV"
              >
                <Download className="h-4 w-4" />
              </Button>
              <Button 
                variant="outline" 
                size="icon" 
                data-testid="button-download-pdf"
                onClick={handleDownloadPdf}
                disabled={isGeneratingPdf}
                title="Descargar PDF"
              >
                {isGeneratingPdf ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <FileText className="h-4 w-4" />
                )}
              </Button>
              <Button 
                variant={isSaved ? "default" : "outline"} 
                size="sm" 
                className="gap-2" 
                onClick={handleSaveToggle}
                disabled={isSaving || !queryId}
                data-testid="button-save-query"
              >
                {isSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : isSaved ? (
                  <BookmarkCheck className="h-4 w-4" />
                ) : (
                  <Bookmark className="h-4 w-4" />
                )}
                {isSaved ? "Guardada" : "Guardar"}
              </Button>
              {isCustomerData && (
                <>
                  <Button 
                    variant="outline" 
                    size="sm" 
                    className="gap-2" 
                    onClick={() => {
                      setSegmentName(query.slice(0, 50));
                      setShowSegmentDialog(true);
                    }}
                    data-testid="button-create-segment"
                  >
                    <Users className="h-4 w-4" />
                    Crear Segmento
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    onClick={handleSendToGhl}
                    disabled={isSendingToGhl}
                    data-testid="button-send-ghl"
                  >
                    {isSendingToGhl ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                    {isSendingToGhl ? "Sending..." : "Send to GHL"}
                  </Button>
                </>
              )}
              {onDrillDown && data.length > 0 && !isRecommendation && (
                <Button
                  variant={isDrillDownMode ? "secondary" : "outline"}
                  size="sm"
                  className="gap-2 border-primary/30 text-primary hover:bg-primary/10"
                  onClick={onDrillDown}
                  data-testid="button-drill-down"
                >
                  <Filter className="h-4 w-4" />
                  {isDrillDownMode ? "Drilling..." : "Drill into Segment"}
                </Button>
              )}
            </div>
          </div>

          {showSql && sql && (
            <div className="relative">
              <pre className="p-4 bg-muted rounded-lg overflow-x-auto text-xs font-mono">
                <code>{sql}</code>
              </pre>
              <Button
                variant="ghost"
                size="icon"
                className="absolute top-2 right-2"
                onClick={() => navigator.clipboard.writeText(sql)}
              >
                <Copy className="h-3 w-3" />
              </Button>
            </div>
          )}

          <div className="min-h-[300px]">{renderChart()}</div>
          </>
          )}
        </div>
      </CardContent>

      <Dialog open={showSegmentDialog} onOpenChange={setShowSegmentDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Crear Segmento</DialogTitle>
            <DialogDescription>
              Convierte estos {data.length} clientes en un segmento que podrás exportar a tu CRM.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="segment-name">Nombre del segmento</Label>
              <Input
                id="segment-name"
                placeholder="Ej: Clientes inactivos 60 días"
                value={segmentName}
                onChange={(e) => setSegmentName(e.target.value)}
                data-testid="input-segment-name"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowSegmentDialog(false)}
              disabled={isCreatingSegment}
            >
              Cancelar
            </Button>
            <Button
              onClick={handleCreateSegment}
              disabled={isCreatingSegment || !segmentName.trim()}
              data-testid="button-confirm-segment"
            >
              {isCreatingSegment ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Creando...
                </>
              ) : (
                <>
                  <Users className="h-4 w-4 mr-2" />
                  Crear Segmento
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showGhlDialog} onOpenChange={setShowGhlDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>GoHighLevel Sync Results</DialogTitle>
            <DialogDescription>
              Summary of contacts sent to your GoHighLevel CRM
            </DialogDescription>
          </DialogHeader>
          {ghlResult && (
            <div className="space-y-4 py-4">
              <div className="grid grid-cols-3 gap-4">
                <div className="text-center p-3 rounded-lg bg-muted/50">
                  <p className="text-2xl font-bold">{ghlResult.total}</p>
                  <p className="text-xs text-muted-foreground">Total</p>
                </div>
                <div className="text-center p-3 rounded-lg bg-muted/50">
                  <p className="text-2xl font-bold text-green-500">{ghlResult.created + ghlResult.updated}</p>
                  <p className="text-xs text-muted-foreground">Synced</p>
                </div>
                <div className="text-center p-3 rounded-lg bg-muted/50">
                  <p className="text-2xl font-bold text-destructive">{ghlResult.failed}</p>
                  <p className="text-xs text-muted-foreground">Failed</p>
                </div>
              </div>
              <Progress 
                value={((ghlResult.created + ghlResult.updated) / ghlResult.total) * 100} 
                className="h-2"
              />
              {(ghlResult.duplicatesRemoved ?? 0) > 0 && (
                <p className="text-xs text-muted-foreground">
                  {ghlResult.duplicatesRemoved} duplicate contacts were skipped before sending.
                </p>
              )}
              {ghlResult.errors.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-sm text-destructive">
                    <AlertTriangle className="h-4 w-4" />
                    Errors ({ghlResult.errors.length})
                  </div>
                  <div className="text-xs text-muted-foreground space-y-1 max-h-32 overflow-y-auto">
                    {ghlResult.errors.map((err, i) => (
                      <p key={i}>{err}</p>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setShowGhlDialog(false)} data-testid="button-close-ghl-results">
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
