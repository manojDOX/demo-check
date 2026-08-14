import { useState, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip as ShadTooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { KpiCard } from "@/components/kpi-card";
import { ClientSelector } from "@/components/client-selector";
import { DateRangeFilter, DateRangeValue, getDefaultDateRange } from "@/components/date-range-filter";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import { apiRequest } from "@/lib/queryClient";
import {
  AreaChart,
  Area,
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
  ReferenceLine,
} from "recharts";
import {
  BarChart3,
  DollarSign,
  ShoppingCart,
  Receipt,
  Users,
  UserPlus,
  RefreshCw,
  Package,
  TrendingUp,
  TrendingDown,
  ArrowUpRight,
  ArrowDownRight,
  Calendar,
  Download,
  Database,
  AlertCircle,
  UserMinus,
  Info,
} from "lucide-react";
import type { Client } from "@shared/schema";

interface BigQueryKpis {
  totalSales: number;
  orderCount: number;
  averageOrderValue: number;
  newCustomers: number;
  recurringCustomers: number;
  recurrenceRate: number;
  customerLtv: number;
  changes: {
    totalSales: number;
    orderCount: number;
    averageOrderValue: number;
    newCustomers: number;
    recurringCustomers: number;
    recurrenceRate: number;
    customerLtv: number;
  };
  period: { from: string; to: string };
  source: string;
}

interface TrendData {
  salesTrend: { date: string; sales: number; orders: number }[];
  customerTrend: { date: string; newCustomers: number; returningCustomers: number }[];
}

interface ProductAnalyticsData {
  topProducts: { planName: string; productId: string; revenue: number; subscriptions: number; avgAmount: number }[];
  statusBreakdown: { status: string; count: number; revenue: number }[];
  intervalBreakdown: { interval: string; count: number; revenue: number }[];
  productTrend: { date: string; planName: string; revenue: number; count: number }[];
}

interface ChurnAnalyticsData {
  summary: { totalStart: number; totalCanceled: number; churnRate: number; canceledRevenue: number };
  monthlyTrend: { month: string; monthLabel: string; monthShortLabel: string; activeStart: number; canceled: number; churnRate: number }[];
  churnByProduct: { planName: string; productId: string; total: number; canceled: number; churnRate: number; canceledRevenue: number }[];
  periodComparison: { currentRate: number; previousRate: number; change: number };
}

const PRODUCT_NAME_MAP: Record<string, string> = {
  "prod_LQjx67EvzQ1PGQ": "Basic Wash",
  "prod_LQjy3uY1m2leN3": "Premium Wash",
  "prod_QokBj7SE3bnVgn": "BW / Road Assistance",
  "prod_TEj2sqBLZUBBby": "BW / Road Assistance Yearly",
};

function getProductDisplayName(raw: string): string {
  return PRODUCT_NAME_MAP[raw] || raw;
}

function ChartInfoTooltip({ text, id }: { text: string; id?: string }) {
  return (
    <TooltipProvider delayDuration={200}>
      <ShadTooltip>
        <TooltipTrigger asChild>
          <Info className="h-4 w-4 text-muted-foreground/60 cursor-help shrink-0" data-testid={id ? `tooltip-${id}` : undefined} />
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-[280px] text-xs font-normal">
          {text}
        </TooltipContent>
      </ShadTooltip>
    </TooltipProvider>
  );
}

const STATUS_COLORS: Record<string, string> = {
  active: "hsl(142, 71%, 45%)",
  canceled: "hsl(0, 84%, 60%)",
  past_due: "hsl(38, 92%, 50%)",
  trialing: "hsl(217, 91%, 60%)",
  incomplete: "hsl(280, 65%, 60%)",
  incomplete_expired: "hsl(0, 0%, 50%)",
  unpaid: "hsl(25, 95%, 53%)",
  paused: "hsl(200, 18%, 46%)",
  unknown: "hsl(0, 0%, 60%)",
};

const INTERVAL_COLORS = [
  "hsl(217, 91%, 60%)",
  "hsl(142, 71%, 45%)",
  "hsl(38, 92%, 50%)",
  "hsl(280, 65%, 60%)",
  "hsl(199, 89%, 48%)",
  "hsl(0, 84%, 60%)",
];

export default function Analytics() {
  const [selectedClientId, setSelectedClientId] = useState<number | null>(null);
  const [dateRange, setDateRange] = useState<DateRangeValue>(getDefaultDateRange());
  const [bigQueryKpis, setBigQueryKpis] = useState<BigQueryKpis | null>(null);
  const [trendData, setTrendData] = useState<TrendData | null>(null);
  const [productData, setProductData] = useState<ProductAnalyticsData | null>(null);
  const [churnData, setChurnData] = useState<ChurnAnalyticsData | null>(null);
  const [hasAutoSelected, setHasAutoSelected] = useState(false);

  const { data: clients, isLoading: isLoadingClients } = useQuery<Client[]>({
    queryKey: ["/api/clients"],
  });

  useEffect(() => {
    if (!hasAutoSelected && clients && clients.length > 0 && selectedClientId === null) {
      const clientWithConnection = clients.find(c => c.connectionId !== null);
      const clientToSelect = clientWithConnection || clients[0];
      setSelectedClientId(clientToSelect.id);
      setHasAutoSelected(true);
    }
  }, [clients, selectedClientId, hasAutoSelected]);

  useEffect(() => {
    if (clients && clients.length > 0 && selectedClientId !== null) {
      const clientExists = clients.some(c => c.id === selectedClientId);
      if (!clientExists) {
        const clientWithConnection = clients.find(c => c.connectionId !== null);
        setSelectedClientId((clientWithConnection || clients[0]).id);
      }
    }
  }, [clients, selectedClientId]);

  const calculateKpisMutation = useMutation({
    mutationFn: async (params: { clientId: number; dateFrom: string; dateTo: string }) => {
      const response = await apiRequest("POST", "/api/kpis/calculate", params);
      return response.json() as Promise<BigQueryKpis>;
    },
    onSuccess: (data) => setBigQueryKpis(data),
    onError: () => setBigQueryKpis(null),
  });

  const calculateTrendsMutation = useMutation({
    mutationFn: async (params: { clientId: number; dateFrom: string; dateTo: string }) => {
      const response = await apiRequest("POST", "/api/kpis/trends", params);
      return response.json() as Promise<TrendData>;
    },
    onSuccess: (data) => setTrendData(data),
    onError: () => setTrendData(null),
  });

  const productAnalyticsMutation = useMutation({
    mutationFn: async (params: { clientId: number; dateFrom: string; dateTo: string }) => {
      const response = await apiRequest("POST", "/api/kpis/product-analytics", params);
      return response.json() as Promise<ProductAnalyticsData>;
    },
    onSuccess: (data) => setProductData(data),
    onError: () => setProductData(null),
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
      const params = {
        clientId: selectedClientId,
        dateFrom: format(dateRange.from, "yyyy-MM-dd"),
        dateTo: format(dateRange.to, "yyyy-MM-dd"),
      };
      calculateKpisMutation.mutate(params);
      calculateTrendsMutation.mutate(params);
      productAnalyticsMutation.mutate(params);
      churnAnalyticsMutation.mutate(params);
    } else {
      setBigQueryKpis(null);
      setTrendData(null);
      setProductData(null);
      setChurnData(null);
    }
  }, [selectedClientId, dateRange]);

  const selectedClient = clients?.find(c => c.id === selectedClientId);
  const hasConnection = selectedClient?.connectionId !== null && selectedClient?.connectionId !== undefined;
  const hasKpiData = bigQueryKpis !== null;
  const isLoadingKpis = calculateKpisMutation.isPending;
  const isLoadingTrends = calculateTrendsMutation.isPending;
  const isLoadingProducts = productAnalyticsMutation.isPending;
  const isLoadingChurn = churnAnalyticsMutation.isPending;
  const hasProductData = productData !== null && productData.topProducts.length > 0;
  const hasChurnData = churnData !== null;

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
      title: "Orders",
      value: hasKpiData ? bigQueryKpis.orderCount.toLocaleString() : "--",
      change: hasKpiData ? bigQueryKpis.changes.orderCount : 0,
      icon: ShoppingCart,
      iconColor: "text-blue-500",
      tooltip: "Cantidad total de suscripciones creadas durante el periodo seleccionado.",
    },
    {
      title: "Avg Order Value",
      value: hasKpiData ? `$${bigQueryKpis.averageOrderValue.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "--",
      change: hasKpiData ? bigQueryKpis.changes.averageOrderValue : 0,
      icon: Receipt,
      iconColor: "text-purple-500",
      tooltip: "Valor promedio de cada suscripcion. Se calcula dividiendo las ventas totales entre la cantidad de suscripciones.",
    },
    {
      title: "New Customers",
      value: hasKpiData ? bigQueryKpis.newCustomers.toLocaleString() : "--",
      change: hasKpiData ? bigQueryKpis.changes.newCustomers : 0,
      icon: UserPlus,
      iconColor: "text-emerald-500",
      tooltip: "Clientes que crearon su primera suscripcion durante el periodo seleccionado (no tenian suscripciones anteriores).",
    },
    {
      title: "Recurring Customers",
      value: hasKpiData ? bigQueryKpis.recurringCustomers.toLocaleString() : "--",
      change: hasKpiData ? bigQueryKpis.changes.recurringCustomers : 0,
      icon: Users,
      iconColor: "text-amber-500",
      tooltip: "Clientes que ya tenian una suscripcion anterior y crearon una nueva suscripcion adicional durante este periodo.",
    },
    {
      title: "Recurrence Rate",
      value: hasKpiData ? `${bigQueryKpis.recurrenceRate.toFixed(1)}%` : "--",
      change: hasKpiData ? bigQueryKpis.changes.recurrenceRate : 0,
      icon: RefreshCw,
      iconColor: "text-cyan-500",
      tooltip: "Porcentaje de clientes recurrentes sobre el total de clientes en el periodo. Indica la retencion y fidelizacion.",
    },
    {
      title: "Customer LTV",
      value: hasKpiData ? `$${bigQueryKpis.customerLtv.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "--",
      change: hasKpiData ? bigQueryKpis.changes.customerLtv : 0,
      icon: TrendingUp,
      iconColor: "text-indigo-500",
      tooltip: "Valor de vida del cliente: promedio del ingreso total historico por cliente que tuvo suscripciones en el periodo. Suma todos los pagos de cada cliente a lo largo de su historia.",
    },
  ];

  const formatChartDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return format(d, "dd MMM", { locale: es });
    } catch {
      return dateStr;
    }
  };

  const salesChartData = trendData?.salesTrend.map(d => ({
    ...d,
    label: formatChartDate(d.date),
  })) || [];

  const customerChartData = trendData?.customerTrend.map(d => ({
    ...d,
    label: formatChartDate(d.date),
  })) || [];

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <BarChart3 className="h-6 w-6 text-primary" />
            KPI Analytics
          </h1>
          <p className="text-muted-foreground mt-1">
            Deep dive into your retail performance metrics
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <ClientSelector
            selectedClientId={selectedClientId}
            onClientChange={setSelectedClientId}
            clients={clients}
            isLoadingClients={isLoadingClients}
          />
          <Button variant="outline" size="sm" className="gap-2" data-testid="button-export-analytics">
            <Download className="h-4 w-4" />
            Export
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <DateRangeFilter
          value={dateRange}
          onChange={setDateRange}
        />
        {hasKpiData && (
          <Badge variant="secondary" className="gap-1.5 bg-green-500/10 text-green-600 border-green-500/20">
            <Database className="h-3 w-3" />
            BigQuery
          </Badge>
        )}
      </div>

      {!hasConnection && selectedClientId && (
        <Card className="border-amber-500/30 bg-amber-500/5">
          <CardContent className="pt-4 pb-4 flex items-center gap-3">
            <AlertCircle className="h-5 w-5 text-amber-500" />
            <p className="text-sm text-amber-600">
              Selecciona un cliente con conexion BigQuery para ver KPIs reales
            </p>
          </CardContent>
        </Card>
      )}

      {hasConnection && calculateKpisMutation.isError && (
        <Card className="border-amber-500/30 bg-amber-500/5">
          <CardContent className="pt-4 pb-4 flex items-center gap-3">
            <AlertCircle className="h-5 w-5 text-amber-500" />
            <p className="text-sm text-amber-600">
              Error al conectar con BigQuery. Las credenciales pueden ser invalidas.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {isLoadingKpis ? (
          <>
            {[...Array(9)].map((_, i) => (
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
            <KpiCard key={kpi.title} {...kpi} isLoading={false} />
          ))
        )}
      </div>

      <Tabs defaultValue="sales" className="space-y-6">
        <TabsList className="bg-muted p-1">
          <TabsTrigger value="sales" data-testid="tab-sales">Sales Trends</TabsTrigger>
          <TabsTrigger value="customers" data-testid="tab-customers">Customer Analysis</TabsTrigger>
          <TabsTrigger value="products" data-testid="tab-products">Product Performance</TabsTrigger>
        </TabsList>

        <TabsContent value="sales" className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5 text-primary" />
                  Sales & Orders Trend
                  <ChartInfoTooltip id="sales-orders-trend" text="Tendencia de ventas totales y cantidad de suscripciones creadas por mes durante el periodo seleccionado." />
                </CardTitle>
                <Badge variant="secondary">
                  <Calendar className="h-3 w-3 mr-1" />
                  {format(dateRange.from, "dd MMM", { locale: es })} - {format(dateRange.to, "dd MMM yyyy", { locale: es })}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="pl-2 pr-4">
              {isLoadingTrends ? (
                <div className="flex items-center justify-center h-[350px]">
                  <Skeleton className="h-full w-full" />
                </div>
              ) : salesChartData.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-[350px] text-center">
                  <div className="h-16 w-16 rounded-full bg-muted flex items-center justify-center mb-4">
                    <TrendingUp className="h-8 w-8 text-muted-foreground" />
                  </div>
                  <h3 className="text-lg font-semibold mb-2">Sin datos de tendencia</h3>
                  <p className="text-sm text-muted-foreground max-w-md">
                    Conecta un cliente con BigQuery y selecciona un rango de fechas para ver tendencias de ventas.
                  </p>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={350}>
                  <AreaChart data={salesChartData} margin={{ top: 10, right: 20, left: -25, bottom: 5 }}>
                    <defs>
                      <linearGradient id="colorSales" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="hsl(217, 91%, 60%)" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="hsl(217, 91%, 60%)" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="colorOrders" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="hsl(199, 89%, 48%)" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="hsl(199, 89%, 48%)" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis
                      dataKey="label"
                      tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                      axisLine={{ stroke: "hsl(var(--border))" }}
                    />
                    <YAxis
                      yAxisId="left"
                      tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                      axisLine={{ stroke: "hsl(var(--border))" }}
                      tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                    />
                    <YAxis
                      yAxisId="right"
                      orientation="right"
                      tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                      axisLine={{ stroke: "hsl(var(--border))" }}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "hsl(var(--card))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: "var(--radius)",
                      }}
                      formatter={(value: number, name: string) => [
                        name === "sales" ? `$${value.toLocaleString("es-MX", { minimumFractionDigits: 2 })}` : value.toLocaleString(),
                        name === "sales" ? "Ventas" : "Ordenes"
                      ]}
                    />
                    <Legend formatter={(value: string) => value === "sales" ? "Ventas" : "Ordenes"} />
                    <Area
                      yAxisId="left"
                      type="monotone"
                      dataKey="sales"
                      stroke="hsl(217, 91%, 60%)"
                      fillOpacity={1}
                      fill="url(#colorSales)"
                      strokeWidth={2}
                    />
                    <Area
                      yAxisId="right"
                      type="monotone"
                      dataKey="orders"
                      stroke="hsl(199, 89%, 48%)"
                      fillOpacity={1}
                      fill="url(#colorOrders)"
                      strokeWidth={2}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="customers" className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <CardTitle className="flex items-center gap-2">
                  <Users className="h-5 w-5 text-primary" />
                  New vs Returning Customers
                  <ChartInfoTooltip id="new-vs-returning" text="Nuevos: clientes con su primera suscripcion en ese mes. Recurrentes: clientes que ya tenian una suscripcion anterior y crearon una adicional." />
                </CardTitle>
                <Badge variant="secondary">
                  <Calendar className="h-3 w-3 mr-1" />
                  {format(dateRange.from, "dd MMM", { locale: es })} - {format(dateRange.to, "dd MMM yyyy", { locale: es })}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="pl-2 pr-4">
              {isLoadingTrends ? (
                <div className="flex items-center justify-center h-[350px]">
                  <Skeleton className="h-full w-full" />
                </div>
              ) : customerChartData.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-[350px] text-center">
                  <div className="h-16 w-16 rounded-full bg-muted flex items-center justify-center mb-4">
                    <Users className="h-8 w-8 text-muted-foreground" />
                  </div>
                  <h3 className="text-lg font-semibold mb-2">Sin datos de clientes</h3>
                  <p className="text-sm text-muted-foreground max-w-md">
                    Conecta un cliente con BigQuery para ver el analisis de clientes nuevos vs recurrentes.
                  </p>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={350}>
                  <BarChart data={customerChartData} margin={{ top: 10, right: 20, left: -25, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis
                      dataKey="label"
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
                      formatter={(value: number, name: string) => [
                        value.toLocaleString(),
                        name === "newCustomers" ? "Nuevos" : "Recurrentes"
                      ]}
                    />
                    <Legend formatter={(value: string) => value === "newCustomers" ? "Nuevos" : "Recurrentes"} />
                    <Bar dataKey="newCustomers" name="newCustomers" fill="hsl(142, 71%, 45%)" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="returningCustomers" name="returningCustomers" fill="hsl(217, 91%, 60%)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="products" className="space-y-6" data-testid="tab-content-products">
          {isLoadingProducts ? (
            <div className="grid gap-4 lg:grid-cols-2">
              {[...Array(4)].map((_, i) => (
                <Card key={i}>
                  <CardHeader>
                    <Skeleton className="h-5 w-40" />
                  </CardHeader>
                  <CardContent>
                    <Skeleton className="h-[250px] w-full" />
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : !hasProductData ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <div className="h-16 w-16 rounded-full bg-muted flex items-center justify-center mb-4">
                  <Package className="h-8 w-8 text-muted-foreground" />
                </div>
                <h3 className="text-lg font-semibold mb-2">Sin datos de productos</h3>
                <p className="text-sm text-muted-foreground text-center max-w-md">
                  Conecta un cliente con BigQuery y selecciona un rango de fechas para ver el rendimiento de productos.
                </p>
              </CardContent>
            </Card>
          ) : (
            <>
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <CardTitle className="flex items-center gap-2">
                      <Package className="h-5 w-5 text-primary" />
                      Top Plans / Products
                      <ChartInfoTooltip id="top-plans" text="Ranking de planes o productos ordenados por ingresos totales. Muestra suscripciones activas, ingresos y precio promedio por plan." />
                    </CardTitle>
                    <Badge variant="secondary">
                      {productData!.topProducts.length} plans
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm" data-testid="table-top-products">
                      <thead>
                        <tr className="border-b border-border">
                          <th className="text-left py-3 px-2 font-medium text-muted-foreground">Plan</th>
                          <th className="text-right py-3 px-2 font-medium text-muted-foreground">Revenue</th>
                          <th className="text-right py-3 px-2 font-medium text-muted-foreground">Subs</th>
                          <th className="text-right py-3 px-2 font-medium text-muted-foreground">Avg Amount</th>
                          <th className="text-right py-3 px-2 font-medium text-muted-foreground">Share</th>
                        </tr>
                      </thead>
                      <tbody>
                        {productData!.topProducts.map((p, i) => {
                          const totalRevenue = productData!.topProducts.reduce((sum, item) => sum + item.revenue, 0);
                          const share = totalRevenue > 0 ? (p.revenue / totalRevenue * 100) : 0;
                          return (
                            <tr key={i} className="border-b border-border/50" data-testid={`row-product-${i}`}>
                              <td className="py-3 px-2">
                                <span className="font-medium">{getProductDisplayName(p.planName)}</span>
                              </td>
                              <td className="text-right py-3 px-2 font-mono">
                                ${p.revenue.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                              </td>
                              <td className="text-right py-3 px-2">{p.subscriptions.toLocaleString()}</td>
                              <td className="text-right py-3 px-2 font-mono">
                                ${p.avgAmount.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                              </td>
                              <td className="text-right py-3 px-2">
                                <div className="flex items-center justify-end gap-2">
                                  <div className="w-16 h-2 rounded-full bg-muted overflow-hidden">
                                    <div
                                      className="h-full rounded-full bg-primary"
                                      style={{ width: `${Math.min(share, 100)}%` }}
                                    />
                                  </div>
                                  <span className="text-muted-foreground text-xs w-12 text-right">{share.toFixed(1)}%</span>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>

              <div className="grid gap-4 lg:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-base">
                      Subscription Status
                      <ChartInfoTooltip id="subscription-status" text="Distribucion de suscripciones por estado: activas, canceladas, vencidas, en prueba, etc." />
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="pl-2 pr-4">
                    <ResponsiveContainer width="100%" height={280}>
                      <PieChart>
                        <Pie
                          data={productData!.statusBreakdown}
                          dataKey="count"
                          nameKey="status"
                          cx="50%"
                          cy="50%"
                          innerRadius={60}
                          outerRadius={100}
                          paddingAngle={2}
                        >
                          {productData!.statusBreakdown.map((entry, index) => (
                            <Cell
                              key={index}
                              fill={STATUS_COLORS[entry.status] || STATUS_COLORS.unknown}
                            />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={{
                            backgroundColor: "hsl(var(--card))",
                            border: "1px solid hsl(var(--border))",
                            borderRadius: "var(--radius)",
                          }}
                          formatter={(value: number, name: string) => [
                            value.toLocaleString(),
                            name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ")
                          ]}
                        />
                        <Legend
                          formatter={(value: string) =>
                            value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, " ")
                          }
                        />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="space-y-2 mt-2">
                      {productData!.statusBreakdown.map((s, i) => (
                        <div key={i} className="flex items-center justify-between text-sm">
                          <div className="flex items-center gap-2">
                            <div
                              className="w-3 h-3 rounded-full"
                              style={{ backgroundColor: STATUS_COLORS[s.status] || STATUS_COLORS.unknown }}
                            />
                            <span className="capitalize">{s.status.replace(/_/g, " ")}</span>
                          </div>
                          <div className="flex items-center gap-4">
                            <span className="text-muted-foreground">{s.count} subs</span>
                            <span className="font-mono">${s.revenue.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-base">
                      Billing Interval
                      <ChartInfoTooltip id="billing-interval" text="Cantidad de suscripciones agrupadas por frecuencia de cobro: mensual, anual, semanal, etc." />
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="pl-2 pr-4">
                    <ResponsiveContainer width="100%" height={280}>
                      <BarChart data={productData!.intervalBreakdown} margin={{ top: 10, right: 10, left: -25, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                        <XAxis
                          dataKey="interval"
                          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                          axisLine={{ stroke: "hsl(var(--border))" }}
                          tickFormatter={(v: string) => v.charAt(0).toUpperCase() + v.slice(1)}
                        />
                        <YAxis
                          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                          axisLine={{ stroke: "hsl(var(--border))" }}
                          tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: "hsl(var(--card))",
                            border: "1px solid hsl(var(--border))",
                            borderRadius: "var(--radius)",
                          }}
                          formatter={(value: number, name: string) => [
                            name === "revenue"
                              ? `$${value.toLocaleString("es-MX", { minimumFractionDigits: 2 })}`
                              : value.toLocaleString(),
                            name === "revenue" ? "Revenue" : "Count"
                          ]}
                        />
                        <Bar dataKey="revenue" fill="hsl(217, 91%, 60%)" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                    <div className="space-y-2 mt-4">
                      {productData!.intervalBreakdown.map((item, i) => (
                        <div key={i} className="flex items-center justify-between text-sm">
                          <div className="flex items-center gap-2">
                            <div
                              className="w-3 h-3 rounded-full"
                              style={{ backgroundColor: INTERVAL_COLORS[i % INTERVAL_COLORS.length] }}
                            />
                            <span className="capitalize">{item.interval}</span>
                          </div>
                          <div className="flex items-center gap-4">
                            <span className="text-muted-foreground">{item.count} subs</span>
                            <span className="font-mono">${item.revenue.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </div>

              {(() => {
                const dates = Array.from(new Set(productData!.productTrend.map(d => d.date))).sort();
                const plans = Array.from(new Set(productData!.productTrend.map(d => d.planName)));
                const topPlans = plans.slice(0, 5);
                const chartData = dates.map(date => {
                  const row: Record<string, any> = { date, label: formatChartDate(date) };
                  for (const plan of topPlans) {
                    const match = productData!.productTrend.find(d => d.date === date && d.planName === plan);
                    row[plan] = match ? match.revenue : 0;
                  }
                  return row;
                });
                const trendColors = [
                  "hsl(217, 91%, 60%)",
                  "hsl(142, 71%, 45%)",
                  "hsl(38, 92%, 50%)",
                  "hsl(280, 65%, 60%)",
                  "hsl(199, 89%, 48%)",
                ];
                return chartData.length > 0 ? (
                  <Card>
                    <CardHeader>
                      <div className="flex items-center justify-between gap-2 flex-wrap">
                        <CardTitle className="flex items-center gap-2">
                          <TrendingUp className="h-5 w-5 text-primary" />
                          Revenue by Plan Over Time
                          <ChartInfoTooltip id="revenue-by-plan" text="Ingresos mensuales desglosados por plan/producto. Muestra como cada plan contribuye a los ingresos totales a lo largo del tiempo." />
                        </CardTitle>
                        <Badge variant="secondary">
                          <Calendar className="h-3 w-3 mr-1" />
                          {format(dateRange.from, "dd MMM", { locale: es })} - {format(dateRange.to, "dd MMM yyyy", { locale: es })}
                        </Badge>
                      </div>
                    </CardHeader>
                    <CardContent className="pl-2 pr-4">
                      <ResponsiveContainer width="100%" height={350}>
                        <AreaChart data={chartData} margin={{ top: 10, right: 20, left: -25, bottom: 5 }}>
                          <defs>
                            {topPlans.map((plan, i) => (
                              <linearGradient key={plan} id={`colorPlan${i}`} x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor={trendColors[i % trendColors.length]} stopOpacity={0.3} />
                                <stop offset="95%" stopColor={trendColors[i % trendColors.length]} stopOpacity={0} />
                              </linearGradient>
                            ))}
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                          <XAxis
                            dataKey="label"
                            tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                            axisLine={{ stroke: "hsl(var(--border))" }}
                          />
                          <YAxis
                            tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                            axisLine={{ stroke: "hsl(var(--border))" }}
                            tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
                          />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: "hsl(var(--card))",
                              border: "1px solid hsl(var(--border))",
                              borderRadius: "var(--radius)",
                            }}
                            formatter={(value: number) => [
                              `$${value.toLocaleString("es-MX", { minimumFractionDigits: 2 })}`,
                            ]}
                          />
                          <Legend />
                          {topPlans.map((plan, i) => (
                            <Area
                              key={plan}
                              type="monotone"
                              dataKey={plan}
                              name={getProductDisplayName(plan)}
                              stroke={trendColors[i % trendColors.length]}
                              fillOpacity={1}
                              fill={`url(#colorPlan${i})`}
                              strokeWidth={2}
                            />
                          ))}
                        </AreaChart>
                      </ResponsiveContainer>
                    </CardContent>
                  </Card>
                ) : null;
              })()}

              {isLoadingChurn ? (
                <div className="grid gap-4 lg:grid-cols-2 mt-6">
                  {[...Array(3)].map((_, i) => (
                    <Card key={`churn-skel-${i}`}>
                      <CardHeader><Skeleton className="h-5 w-40" /></CardHeader>
                      <CardContent><Skeleton className="h-[250px] w-full" /></CardContent>
                    </Card>
                  ))}
                </div>
              ) : hasChurnData ? (
                <>
                  <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 mt-6" data-testid="churn-kpi-cards">
                    <Card>
                      <CardContent className="pt-6">
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <p className="text-sm text-muted-foreground">Churn Rate</p>
                            <p className="text-2xl font-bold">{churnData!.summary.churnRate}%</p>
                          </div>
                          <div className="h-10 w-10 rounded-full bg-destructive/10 flex items-center justify-center">
                            <UserMinus className="h-5 w-5 text-destructive" />
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <p className="text-sm text-muted-foreground">Cancelaciones</p>
                            <p className="text-2xl font-bold">{churnData!.summary.totalCanceled.toLocaleString()}</p>
                          </div>
                          <div className="h-10 w-10 rounded-full bg-orange-500/10 flex items-center justify-center">
                            <TrendingDown className="h-5 w-5 text-orange-500" />
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <p className="text-sm text-muted-foreground">Revenue Perdido</p>
                            <p className="text-2xl font-bold">${churnData!.summary.canceledRevenue.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
                          </div>
                          <div className="h-10 w-10 rounded-full bg-red-500/10 flex items-center justify-center">
                            <DollarSign className="h-5 w-5 text-red-500" />
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <p className="text-sm text-muted-foreground">vs Periodo Anterior</p>
                            <div className="flex items-center gap-1">
                              <p className="text-2xl font-bold">
                                {churnData!.periodComparison.change > 0 ? "+" : ""}{churnData!.periodComparison.change}%
                              </p>
                              {churnData!.periodComparison.change > 0 ? (
                                <ArrowUpRight className="h-5 w-5 text-destructive" />
                              ) : churnData!.periodComparison.change < 0 ? (
                                <ArrowDownRight className="h-5 w-5 text-green-500" />
                              ) : null}
                            </div>
                            <p className="text-xs text-muted-foreground">
                              Anterior: {churnData!.periodComparison.previousRate}%
                            </p>
                          </div>
                          <div className={`h-10 w-10 rounded-full flex items-center justify-center ${churnData!.periodComparison.change <= 0 ? "bg-green-500/10" : "bg-destructive/10"}`}>
                            {churnData!.periodComparison.change <= 0 ? (
                              <TrendingDown className="h-5 w-5 text-green-500" />
                            ) : (
                              <TrendingUp className="h-5 w-5 text-destructive" />
                            )}
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2 mt-4">
                    {churnData!.monthlyTrend.length > 0 && (
                      <Card className="lg:col-span-2" data-testid="chart-churn-trend">
                        <CardHeader>
                          <div className="flex items-center justify-between gap-2 flex-wrap">
                            <CardTitle className="flex items-center gap-2">
                              <TrendingDown className="h-5 w-5 text-destructive" />
                              Churn Rate Mensual
                              <ChartInfoTooltip id="churn-rate" text="Porcentaje de suscripciones canceladas cada mes respecto a las activas al inicio del mes. Un churn bajo indica mejor retencion de clientes." />
                            </CardTitle>
                            <Badge variant="secondary">
                              <Calendar className="h-3 w-3 mr-1" />
                              Tendencia mes a mes
                            </Badge>
                          </div>
                        </CardHeader>
                        <CardContent className="pl-2 pr-4">
                          <ResponsiveContainer width="100%" height={300}>
                            <LineChart data={churnData!.monthlyTrend.map(d => ({
                              ...d,
                              label: d.monthLabel,
                            }))} margin={{ top: 10, right: 20, left: -25, bottom: 5 }}>
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
                                  if (name === "canceled") return [value, "Cancelados"];
                                  return [value, name];
                                }}
                              />
                              <Legend formatter={(value) => {
                                if (value === "churnRate") return "Churn Rate";
                                if (value === "canceled") return "Cancelados";
                                return value;
                              }} />
                              <Line
                                type="monotone"
                                dataKey="churnRate"
                                stroke="hsl(0, 84%, 60%)"
                                strokeWidth={2}
                                dot={{ fill: "hsl(0, 84%, 60%)", r: 4 }}
                                activeDot={{ r: 6 }}
                              />
                            </LineChart>
                          </ResponsiveContainer>
                          <div className="flex flex-wrap gap-4 mt-4 text-sm">
                            {churnData!.monthlyTrend.map((m, i) => {
                              return (
                                <div key={i} className="flex items-center gap-2 text-muted-foreground">
                                  <span className="font-medium">{m.monthShortLabel}:</span>
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

                    {churnData!.churnByProduct.length > 0 && (
                      <Card className="lg:col-span-2" data-testid="chart-churn-by-product">
                        <CardHeader>
                          <div className="flex items-center justify-between gap-2 flex-wrap">
                            <CardTitle className="flex items-center gap-2">
                              <Package className="h-5 w-5 text-orange-500" />
                              Churn por Producto
                              <ChartInfoTooltip id="churn-by-product" text="Desglose de cancelaciones por plan/producto. Muestra cuantas suscripciones se cancelaron de cada plan y los ingresos perdidos." />
                            </CardTitle>
                            <Badge variant="secondary">
                              {churnData!.churnByProduct.length} productos
                            </Badge>
                          </div>
                        </CardHeader>
                        <CardContent>
                          <div className="grid gap-4 sm:grid-cols-2">
                            <div>
                              <ResponsiveContainer width="100%" height={250}>
                                <BarChart data={churnData!.churnByProduct.map(p => ({
                                  ...p,
                                  name: getProductDisplayName(p.planName),
                                }))} layout="vertical" margin={{ top: 5, right: 30, left: 80, bottom: 5 }}>
                                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                                  <XAxis
                                    type="number"
                                    tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                                    axisLine={{ stroke: "hsl(var(--border))" }}
                                    tickFormatter={(v: number) => `${v}%`}
                                  />
                                  <YAxis
                                    type="category"
                                    dataKey="name"
                                    tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
                                    axisLine={{ stroke: "hsl(var(--border))" }}
                                    width={75}
                                  />
                                  <Tooltip
                                    contentStyle={{
                                      backgroundColor: "hsl(var(--card))",
                                      border: "1px solid hsl(var(--border))",
                                      borderRadius: "var(--radius)",
                                    }}
                                    formatter={(value: number) => [`${value}%`, "Churn Rate"]}
                                  />
                                  <Bar dataKey="churnRate" fill="hsl(0, 84%, 60%)" radius={[0, 4, 4, 0]} />
                                </BarChart>
                              </ResponsiveContainer>
                            </div>
                            <div className="space-y-3">
                              {churnData!.churnByProduct.map((p, i) => (
                                <div key={i} className="flex items-center justify-between gap-2 py-2 border-b border-border/50" data-testid={`row-churn-product-${i}`}>
                                  <div>
                                    <p className="font-medium text-sm">{getProductDisplayName(p.planName)}</p>
                                    <p className="text-xs text-muted-foreground">
                                      {p.canceled} de {p.total} suscripciones
                                    </p>
                                  </div>
                                  <div className="text-right">
                                    <Badge variant={p.churnRate > 5 ? "destructive" : "secondary"}>
                                      {p.churnRate}%
                                    </Badge>
                                    <p className="text-xs text-muted-foreground mt-1">
                                      -${p.canceledRevenue.toLocaleString("es-MX", { minimumFractionDigits: 2 })}
                                    </p>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        </CardContent>
                      </Card>
                    )}
                  </div>
                </>
              ) : null}
            </>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
