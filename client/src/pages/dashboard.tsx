import { useState, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { KpiCard } from "@/components/kpi-card";
import { QueryInput } from "@/components/query-input";
import { ClientSelector } from "@/components/client-selector";
import { DateRangeFilter, DateRangeValue, getDefaultDateRange } from "@/components/date-range-filter";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import { Tooltip as ShadTooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  DollarSign,
  ShoppingCart,
  Receipt,
  Users,
  UserPlus,
  RefreshCw,
  RotateCcw,
  Package,
  TrendingUp,
  TrendingDown,
  ArrowRight,
  Sparkles,
  BarChart3,
  Target,
  BookmarkIcon,
  Trash2,
  AlertCircle,
  Info,
  Database,
  Calendar,
} from "lucide-react";
import { Link } from "wouter";
import type { KpiSnapshot, Segment, Query as QueryType, Client } from "@shared/schema";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { useToast } from "@/hooks/use-toast";
import { useRole } from "@/hooks/use-role";

function DashboardInfoTooltip({ text, id }: { text: string; id: string }) {
  return (
    <TooltipProvider delayDuration={200}>
      <ShadTooltip>
        <TooltipTrigger asChild>
          <Info className="h-4 w-4 text-muted-foreground/60 cursor-help shrink-0" data-testid={`tooltip-${id}`} />
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-[280px] text-xs font-normal">
          {text}
        </TooltipContent>
      </ShadTooltip>
    </TooltipProvider>
  );
}

interface BigQueryKpis {
  totalSales: number;
  activeMemberships: number;
  netMonthlyGrowth: number;
  inactivePercent: number;
  monthlyRecurringRevenue: number;
  averagePurchaseAmount: number;
  changes: {
    totalSales: number;
    activeMemberships: number;
    netMonthlyGrowth: number;
    inactivePercent: number;
    monthlyRecurringRevenue: number;
    averagePurchaseAmount: number;
  };
  period: { from: string; to: string };
  source: string;
}

interface ChurnAnalyticsData {
  summary: { totalStart: number; totalCanceled: number; churnRate: number; canceledRevenue: number };
  monthlyTrend: { month: string; activeStart: number; canceled: number; churnRate: number }[];
  churnByProduct: { planName: string; productId: string; total: number; canceled: number; churnRate: number; canceledRevenue: number }[];
  periodComparison: { currentRate: number; previousRate: number; change: number };
}

const CHART_COLORS = ["hsl(217, 91%, 60%)", "hsl(199, 89%, 48%)"];

// Mini chart component for saved queries
function MiniChart({ query, onRemove }: { query: QueryType; onRemove: (id: number) => void }) {
  const resultData = query.resultData as Array<Record<string, unknown>> | null;
  
  if (!resultData || resultData.length === 0) {
    return null;
  }

  // Get keys for chart
  const keys = Object.keys(resultData[0]);
  const labelKey = keys.find(k => 
    k.toLowerCase().includes("month") || k.toLowerCase().includes("mes") ||
    k.toLowerCase().includes("date") || k.toLowerCase().includes("name")
  ) || keys[0];
  
  const valueKeys = keys.filter(k => {
    if (k === labelKey) return false;
    const lowerKey = k.toLowerCase();
    if (lowerKey === "year" || lowerKey === "año" || lowerKey === "month" || lowerKey === "mes") return false;
    const sample = resultData[0][k];
    return typeof sample === "number" || (typeof sample === "string" && !isNaN(Number(sample)));
  });

  const chartData = resultData.map(row => {
    const formatted: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(row)) {
      if (value && typeof value === "object" && "value" in value) {
        formatted[key] = (value as { value: unknown }).value;
      } else {
        formatted[key] = value;
      }
    }
    return formatted;
  });

  const isLineChart = query.visualizationType === "line";

  return (
    <Card className="relative" data-testid={`saved-chart-${query.id}`}>
      <CardHeader className="pb-2 flex flex-row items-start justify-between gap-2 space-y-0">
        <div className="flex-1 min-w-0">
          <CardTitle className="text-sm font-medium truncate">{query.naturalLanguage}</CardTitle>
          <p className="text-xs text-muted-foreground mt-1 truncate">{query.resultSummary}</p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          onClick={() => onRemove(query.id)}
          data-testid={`button-remove-chart-${query.id}`}
        >
          <Trash2 className="h-4 w-4 text-muted-foreground" />
        </Button>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={150}>
          {isLineChart ? (
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey={labelKey} tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              {valueKeys.slice(0, 2).map((key, idx) => (
                <Line key={key} type="monotone" dataKey={key} stroke={CHART_COLORS[idx]} strokeWidth={2} dot={false} />
              ))}
            </LineChart>
          ) : (
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey={labelKey} tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              {valueKeys.slice(0, 2).map((key, idx) => (
                <Bar key={key} dataKey={key} fill={CHART_COLORS[idx]} radius={[4, 4, 0, 0]} />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

export default function Dashboard() {
  const [selectedClientId, setSelectedClientId] = useState<number | null>(null);
  const [dateRange, setDateRange] = useState<DateRangeValue>(getDefaultDateRange());
  const [bigQueryKpis, setBigQueryKpis] = useState<BigQueryKpis | null>(null);
  const [churnData, setChurnData] = useState<ChurnAnalyticsData | null>(null);
  const [hasAutoSelected, setHasAutoSelected] = useState(false);
  const { toast } = useToast();
  const { isViewer } = useRole();

  // Query clients to auto-select on load
  const { data: clients, isLoading: isLoadingClients } = useQuery<Client[]>({
    queryKey: ["/api/clients"],
  });

  // Auto-select first client when clients load (only once)
  useEffect(() => {
    if (!hasAutoSelected && clients && clients.length > 0 && selectedClientId === null) {
      // Prefer a client with a connection, otherwise pick first
      const clientWithConnection = clients.find(c => c.connectionId !== null);
      const clientToSelect = clientWithConnection || clients[0];
      setSelectedClientId(clientToSelect.id);
      setHasAutoSelected(true);
    }
  }, [clients, selectedClientId, hasAutoSelected]);

  // Recover selection if current client was deleted
  useEffect(() => {
    if (clients && clients.length > 0 && selectedClientId !== null) {
      const clientExists = clients.some(c => c.id === selectedClientId);
      if (!clientExists) {
        // Current client was deleted, select first available
        const clientWithConnection = clients.find(c => c.connectionId !== null);
        setSelectedClientId((clientWithConnection || clients[0]).id);
      }
    }
  }, [clients, selectedClientId]);

  const { data: recentSegments } = useQuery<Segment[]>({
    queryKey: ["/api/segments", { limit: 5 }],
  });

  const { data: recentQueries } = useQuery<QueryType[]>({
    queryKey: ["/api/queries", { limit: 5 }],
  });

  const { data: savedQueries } = useQuery<QueryType[]>({
    queryKey: ["/api/queries/saved"],
  });

  const calculateKpisMutation = useMutation({
    mutationFn: async (params: { clientId: number; dateFrom: string; dateTo: string }) => {
      const response = await apiRequest("POST", "/api/kpis/dashboard", params);
      return response.json() as Promise<BigQueryKpis>;
    },
    onSuccess: (data) => {
      setBigQueryKpis(data);
    },
    onError: (error: any) => {
      console.error("Error calculating KPIs:", error);
      setBigQueryKpis(null);
    },
  });

  const churnAnalyticsMutation = useMutation({
    mutationFn: async (params: { clientId: number; dateFrom: string; dateTo: string }) => {
      const response = await apiRequest("POST", "/api/kpis/churn-analytics", params);
      return response.json() as Promise<ChurnAnalyticsData>;
    },
    onSuccess: (data) => setChurnData(data),
    onError: () => setChurnData(null),
  });

  useEffect(() => {
    if (selectedClientId && dateRange.from && dateRange.to) {
      const dateFrom = format(dateRange.from, "yyyy-MM-dd");
      const dateTo = format(dateRange.to, "yyyy-MM-dd");
      calculateKpisMutation.mutate({ clientId: selectedClientId, dateFrom, dateTo });
      churnAnalyticsMutation.mutate({ clientId: selectedClientId, dateFrom, dateTo });
    } else {
      setBigQueryKpis(null);
      setChurnData(null);
    }
  }, [selectedClientId, dateRange]);

  const handleRemoveSavedChart = async (id: number) => {
    try {
      await apiRequest("PATCH", `/api/queries/${id}/save`, { isSaved: false });
      queryClient.invalidateQueries({ queryKey: ["/api/queries/saved"] });
      toast({ title: "Gráfica removida del dashboard" });
    } catch {
      toast({ title: "Error al remover gráfica", variant: "destructive" });
    }
  };

  const isLoadingKpis = calculateKpisMutation.isPending;
  // Check if the selected client has a BigQuery connection
  const selectedClient = clients?.find(c => c.id === selectedClientId);
  const hasConnection = selectedClient?.connectionId !== null && selectedClient?.connectionId !== undefined;
  const hasKpiData = bigQueryKpis !== null;

  const kpiCards = [
    {
      title: "Total Sales",
      value: hasKpiData ? `$${bigQueryKpis.totalSales.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "--",
      change: hasKpiData ? bigQueryKpis.changes.totalSales : 0,
      icon: DollarSign,
      iconColor: "text-green-500",
      tooltip: "Suma total de ingresos por suscripciones creadas en el periodo seleccionado.",
    },
    {
      title: "Membresías Activas",
      value: hasKpiData ? bigQueryKpis.activeMemberships.toLocaleString() : "--",
      change: hasKpiData ? bigQueryKpis.changes.activeMemberships : 0,
      icon: Users,
      iconColor: "text-blue-500",
      tooltip: "Cantidad de suscripciones activas (no canceladas o canceladas despues del fin del periodo).",
    },
    {
      title: "Crecimiento Neto",
      value: hasKpiData ? `${bigQueryKpis.netMonthlyGrowth >= 0 ? "+" : ""}${bigQueryKpis.netMonthlyGrowth.toLocaleString()}` : "--",
      change: hasKpiData ? bigQueryKpis.changes.netMonthlyGrowth : 0,
      icon: TrendingUp,
      iconColor: "text-emerald-500",
      tooltip: "Diferencia entre nuevas suscripciones y cancelaciones en el periodo. Un numero positivo indica crecimiento.",
    },
    {
      title: "% Inactivos",
      value: hasKpiData ? `${bigQueryKpis.inactivePercent.toFixed(1)}%` : "--",
      change: hasKpiData ? bigQueryKpis.changes.inactivePercent : 0,
      icon: UserPlus,
      iconColor: "text-amber-500",
      tooltip: "Porcentaje de suscripciones canceladas respecto al total de activas e inactivas en el periodo.",
    },
    {
      title: "Monthly RR",
      value: hasKpiData ? `$${bigQueryKpis.monthlyRecurringRevenue.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "--",
      change: hasKpiData ? bigQueryKpis.changes.monthlyRecurringRevenue : 0,
      icon: RefreshCw,
      iconColor: "text-cyan-500",
      tooltip: "Ingreso mensual recurrente: suma de los montos de todas las suscripciones activas al final del periodo.",
    },
    {
      title: "Compra Promedio",
      value: hasKpiData ? `$${bigQueryKpis.averagePurchaseAmount.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "--",
      change: hasKpiData ? bigQueryKpis.changes.averagePurchaseAmount : 0,
      icon: ShoppingCart,
      iconColor: "text-purple-500",
      tooltip: "Monto promedio por transaccion. Se calcula dividiendo las ventas totales entre el numero de suscripciones.",
    },
  ];

  const handleQuery = (query: string) => {
    window.location.href = `/query?q=${encodeURIComponent(query)}`;
  };

  return (
    <div className="p-3 sm:p-6 space-y-8 max-w-7xl mx-auto">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <ClientSelector
          selectedClientId={selectedClientId}
          onClientChange={setSelectedClientId}
          clients={clients}
          isLoadingClients={isLoadingClients}
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm text-muted-foreground hidden sm:flex">
          <Sparkles className="h-4 w-4 text-primary" />
          Ask anything about your data
        </div>
        <QueryInput onSubmit={handleQuery} placeholder="Ask..." />
      </div>

      <div>
        <div className="flex items-center justify-between gap-2 mb-4">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold"><span className="sm:hidden">KPI</span><span className="hidden sm:inline">Key Performance Indicators</span></h2>
            {hasKpiData && (
              <Badge variant="secondary" className="gap-1.5 bg-green-500/10 text-green-600 border-green-500/20">
                <Database className="h-3 w-3" />
                BigQuery
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            <DateRangeFilter
              value={dateRange}
              onChange={setDateRange}
            />
            <Link href="/analytics">
              <Button variant="ghost" size="icon" className="h-9 w-9 shrink-0" title="View All" data-testid="link-view-all-kpis">
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </div>
        </div>

        {!hasConnection && (
          <Card className="mb-4 border-amber-500/30 bg-amber-500/5">
            <CardContent className="pt-4 pb-4 flex items-center gap-3">
              <AlertCircle className="h-5 w-5 text-amber-500" />
              <p className="text-sm text-amber-600">
                Selecciona un cliente con conexión BigQuery para ver KPIs reales
              </p>
            </CardContent>
          </Card>
        )}

        {hasConnection && calculateKpisMutation.isError && (
          <Card className="mb-4 border-amber-500/30 bg-amber-500/5">
            <CardContent className="pt-4 pb-4 flex items-center gap-3">
              <AlertCircle className="h-5 w-5 text-amber-500" />
              <div className="flex-1">
                <p className="text-sm text-amber-600">
                  Error al conectar con BigQuery. Las credenciales pueden ser invalidas.
                </p>
                {!isViewer && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Ve a <Link href="/settings/connections" className="underline">Conexiones</Link> para verificar o actualizar las credenciales de BigQuery.
                  </p>
                )}
                {isViewer && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Contacta al administrador de la cuenta para resolver este problema.
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {hasConnection && churnData && churnData.monthlyTrend.length > 0 && (
          <Card className="mb-4" data-testid="dashboard-churn-chart">
            <CardHeader>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <CardTitle className="flex items-center gap-2">
                  <TrendingDown className="h-5 w-5 text-destructive" />
                  Churn Rate Mensual
                </CardTitle>
                <Badge variant="secondary">
                  <Calendar className="h-3 w-3 mr-1" />
                  Tendencia mes a mes
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={churnData.monthlyTrend.map(d => ({
                  ...d,
                  label: (() => {
                    const dt = new Date(d.month);
                    return format(dt, "MMM yyyy", { locale: es });
                  })(),
                }))} margin={{ top: 10, right: 10, left: -10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis
                    dataKey="label"
                    tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                    axisLine={{ stroke: "hsl(var(--border))" }}
                  />
                  <YAxis
                    tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                    axisLine={{ stroke: "hsl(var(--border))" }}
                    tickFormatter={(v: number) => `${v}%`}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--card))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "var(--radius)",
                    }}
                    formatter={(value: number, name: string) => {
                      if (name === "churnRate") return [`${value}%`, "Churn Rate"];
                      return [value, name];
                    }}
                  />
                  <Legend formatter={(value) => {
                    if (value === "churnRate") return "Churn Rate";
                    return value;
                  }} />
                  <Line
                    type="monotone"
                    dataKey="churnRate"
                    stroke="hsl(0, 84%, 60%)"
                    strokeWidth={2}
                    dot={{ fill: "hsl(0, 84%, 60%)", r: 5 }}
                    activeDot={{ r: 7 }}
                  />
                </LineChart>
              </ResponsiveContainer>
              <div className="flex flex-wrap gap-4 mt-4 text-sm">
                {churnData.monthlyTrend.map((m, i) => {
                  const dt = new Date(m.month);
                  return (
                    <div key={i} className="flex items-center gap-2 text-muted-foreground">
                      <span className="font-medium">{format(dt, "MMM yy", { locale: es })}:</span>
                      <span className="text-foreground">{m.canceled} cancelados</span>
                      <span>de {m.activeStart}</span>
                      <Badge variant={m.churnRate > 5 ? "destructive" : "secondary"} className="text-xs">
                        {m.churnRate}%
                      </Badge>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {hasConnection && churnAnalyticsMutation.isPending && (
          <Card className="mb-4">
            <CardHeader>
              <Skeleton className="h-5 w-48" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-[280px] w-full" />
            </CardContent>
          </Card>
        )}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {isLoadingKpis ? (
            <>
              {[...Array(6)].map((_, i) => (
                <Card key={i}>
                  <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 pb-2">
                    <Skeleton className="h-4 w-24" />
                    <Skeleton className="h-8 w-8 rounded-md" />
                  </CardHeader>
                  <CardContent>
                    <Skeleton className="h-8 w-32 mb-2" />
                    <Skeleton className="h-4 w-20" />
                  </CardContent>
                </Card>
              ))}
            </>
          ) : (
            kpiCards.map((kpi) => (
              <KpiCard
                key={kpi.title}
                {...kpi}
                isLoading={false}
              />
            ))
          )}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
            <div className="flex items-center gap-2">
              <Target className="h-5 w-5 text-primary" />
              <CardTitle className="text-base font-semibold">Active Segments</CardTitle>
              <DashboardInfoTooltip id="active-segments" text="Segmentos de clientes creados para agrupar audiencias. Pueden ser generados por IA o manualmente." />
            </div>
            <Link href="/segments">
              <Button variant="ghost" size="sm" className="gap-1" data-testid="link-view-all-segments">
                View All
                <ArrowRight className="h-3 w-3" />
              </Button>
            </Link>
          </CardHeader>
          <CardContent>
            {!recentSegments || recentSegments.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-center">
                <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center mb-3">
                  <Target className="h-6 w-6 text-muted-foreground" />
                </div>
                <p className="text-sm text-muted-foreground mb-3">
                  No segments created yet
                </p>
                <Link href="/segments">
                  <Button size="sm" data-testid="button-create-first-segment">Create Segment</Button>
                </Link>
              </div>
            ) : (
              <div className="space-y-3">
                {recentSegments.slice(0, 4).map((segment) => (
                  <div
                    key={segment.id}
                    className="flex items-center justify-between p-3 rounded-lg bg-muted/50 hover-elevate transition-colors"
                    data-testid={`segment-item-${segment.id}`}
                  >
                    <div className="flex items-center gap-3">
                      <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                        <Users className="h-4 w-4 text-primary" />
                      </div>
                      <div>
                        <p className="font-medium text-sm">{segment.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {segment.contactCount?.toLocaleString() || 0} contacts
                        </p>
                      </div>
                    </div>
                    <Badge variant={segment.isAiGenerated ? "default" : "secondary"}>
                      {segment.isAiGenerated ? "AI" : "Manual"}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-primary" />
              <CardTitle className="text-base font-semibold">Recent Queries</CardTitle>
              <DashboardInfoTooltip id="recent-queries" text="Historial de preguntas recientes hechas en lenguaje natural sobre tus datos de negocio." />
            </div>
            <Link href="/query">
              <Button variant="ghost" size="sm" className="gap-1" data-testid="link-view-all-queries">
                View All
                <ArrowRight className="h-3 w-3" />
              </Button>
            </Link>
          </CardHeader>
          <CardContent>
            {!recentQueries || recentQueries.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-center">
                <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center mb-3">
                  <Sparkles className="h-6 w-6 text-muted-foreground" />
                </div>
                <p className="text-sm text-muted-foreground mb-3">
                  Start by asking a question about your data
                </p>
                <Link href="/query">
                  <Button size="sm" data-testid="button-ask-first-question">Ask a Question</Button>
                </Link>
              </div>
            ) : (
              <div className="space-y-3">
                {recentQueries.slice(0, 4).map((query) => (
                  <div
                    key={query.id}
                    className="p-3 rounded-lg bg-muted/50 hover-elevate transition-colors cursor-pointer"
                    data-testid={`query-item-${query.id}`}
                  >
                    <p className="text-sm font-medium truncate">{query.naturalLanguage}</p>
                    <p className="text-xs text-muted-foreground mt-1 truncate">
                      {query.resultSummary || "View results"}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Saved Charts Section */}
      {savedQueries && savedQueries.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <BookmarkIcon className="h-5 w-5 text-primary" />
              <h2 className="text-lg font-semibold">Gráficas Guardadas</h2>
            </div>
            <Link href="/query">
              <Button variant="ghost" size="sm" className="gap-1" data-testid="link-add-more-charts">
                Agregar más
                <ArrowRight className="h-3 w-3" />
              </Button>
            </Link>
          </div>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {savedQueries.map((query) => (
              <MiniChart key={query.id} query={query} onRemove={handleRemoveSavedChart} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
