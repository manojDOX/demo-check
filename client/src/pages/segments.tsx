import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ClientSelector } from "@/components/client-selector";
import { Skeleton } from "@/components/ui/skeleton";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { useToast } from "@/hooks/use-toast";
import {
  Users,
  Plus,
  Sparkles,
  Search,
  Filter,
  MoreVertical,
  Send,
  Trash2,
  Edit2,
  Eye,
  Target,
  Zap,
  Calendar,
  Mail,
  RefreshCw,
  X,
  Loader2,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Segment, Client } from "@shared/schema";

interface SegmentMember {
  customer_id?: string;
  email?: string;
  name?: string;
  [key: string]: any;
}

interface SegmentMembersResponse {
  members: SegmentMember[];
  count: number;
  cached: boolean;
  message?: string;
}

interface SegmentCriteria {
  explanation?: string;
  confidence?: number;
  aiGenerated?: boolean;
  [key: string]: any;
}

export default function Segments() {
  const [selectedClientId, setSelectedClientId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [newSegmentName, setNewSegmentName] = useState("");
  const [newSegmentDescription, setNewSegmentDescription] = useState("");
  const [selectedSegment, setSelectedSegment] = useState<Segment | null>(null);
  const [isDetailDialogOpen, setIsDetailDialogOpen] = useState(false);
  const [isExportDialogOpen, setIsExportDialogOpen] = useState(false);
  const [isSendingToGhl, setIsSendingToGhl] = useState(false);
  const [ghlSendResult, setGhlSendResult] = useState<{total: number; created: number; updated: number; failed: number; errors: string[]} | null>(null);
  const { toast } = useToast();

  const { data: segments, isLoading } = useQuery<Segment[]>({
    queryKey: ["/api/segments", selectedClientId],
  });

  const { data: clients } = useQuery<Client[]>({
    queryKey: ["/api/clients"],
  });

  const { data: segmentMembers, isLoading: isLoadingMembers, refetch: refetchMembers } = useQuery<SegmentMembersResponse>({
    queryKey: ["/api/segments", selectedSegment?.id, "members"],
    enabled: !!selectedSegment?.id && isDetailDialogOpen,
  });

  const createSegmentMutation = useMutation({
    mutationFn: async (data: { name: string; description: string; clientId: number | null }) => {
      try {
        const response = await apiRequest("POST", "/api/segments", data);
        return await response.json();
      } catch (err: any) {
        console.error("Create segment error:", err);
        throw err;
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/segments"] });
      setIsCreateDialogOpen(false);
      setNewSegmentName("");
      setNewSegmentDescription("");
      toast({ title: "Segmento creado", description: "El segmento se ha creado correctamente." });
    },
    onError: (error: any) => {
      console.error("Segment creation failed:", error);
      toast({ title: "Error", description: error?.message || "No se pudo crear el segmento.", variant: "destructive" });
    },
  });

  const generateAISegmentMutation = useMutation({
    mutationFn: async () => {
      const response = await apiRequest("POST", "/api/segments/generate", {
        clientId: selectedClientId,
      });
      return response.json();
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["/api/segments"] });
      toast({ 
        title: "Segmento generado por AI", 
        description: `Se ha creado el segmento "${data.name}" con ${data.contactCount || 0} contactos.` 
      });
    },
    onError: (error: any) => {
      toast({ 
        title: "Error", 
        description: error.message || "No se pudo generar el segmento. Verifica tu conexion a BigQuery.", 
        variant: "destructive" 
      });
    },
  });

  const deleteSegmentMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await apiRequest("DELETE", `/api/segments/${id}`);
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/segments"] });
      setIsDetailDialogOpen(false);
      setSelectedSegment(null);
      toast({ title: "Segmento eliminado", description: "El segmento se ha eliminado correctamente." });
    },
    onError: () => {
      toast({ title: "Error", description: "No se pudo eliminar el segmento.", variant: "destructive" });
    },
  });

  const filteredSegments = segments?.filter((segment) =>
    segment.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleCreateSegment = () => {
    if (!newSegmentName.trim()) return;
    createSegmentMutation.mutate({
      name: newSegmentName,
      description: newSegmentDescription,
      clientId: selectedClientId,
    });
  };

  const handleSegmentClick = (segment: Segment) => {
    setSelectedSegment(segment);
    setIsDetailDialogOpen(true);
  };

  const handleDeleteSegment = (id: number) => {
    if (confirm("¿Estas seguro de que deseas eliminar este segmento?")) {
      deleteSegmentMutation.mutate(id);
    }
  };

  const handleExportToGhl = (segment: Segment) => {
    setSelectedSegment(segment);
    setGhlSendResult(null);
    setIsExportDialogOpen(true);
  };

  const handleConfirmSendToGhl = async () => {
    if (!selectedSegment) return;
    setIsSendingToGhl(true);
    setGhlSendResult(null);

    try {
      const settingsRes = await fetch("/api/ghl/settings", { credentials: "include" });
      const settings = await settingsRes.json();
      if (!settings.isConfigured) {
        toast({
          title: "GHL no configurado",
          description: "GoHighLevel no esta configurado. Contacta al administrador.",
          variant: "destructive",
        });
        setIsSendingToGhl(false);
        return;
      }

      const membersResponse = await apiRequest("GET", `/api/segments/${selectedSegment.id}/members`);
      const membersData: SegmentMembersResponse = await membersResponse.json();

      if (!membersData.members || membersData.members.length === 0) {
        toast({
          title: "Sin contactos",
          description: "Este segmento no tiene contactos para enviar.",
          variant: "destructive",
        });
        setIsSendingToGhl(false);
        return;
      }

      const contacts = membersData.members.map(member => {
        const contact: Record<string, string> = {};
        if (member.name) contact.name = String(member.name);
        if (member.email) contact.email = String(member.email);
        if (member.phone) contact.phone = String(member.phone);
        if (member.firstName || member.first_name) contact.firstName = String(member.firstName || member.first_name);
        if (member.lastName || member.last_name) contact.lastName = String(member.lastName || member.last_name);
        return contact;
      }).filter(c => c.email || c.phone || c.name || c.firstName);

      if (contacts.length === 0) {
        toast({
          title: "Sin datos de contacto",
          description: "Los contactos del segmento no tienen email, telefono o nombre.",
          variant: "destructive",
        });
        setIsSendingToGhl(false);
        return;
      }

      const segmentTag = selectedSegment.name;
      const BATCH_SIZE = 500;
      const totalBatches = Math.ceil(contacts.length / BATCH_SIZE);
      const aggregated = { total: contacts.length, created: 0, updated: 0, failed: 0, errors: [] as string[] };

      for (let i = 0; i < totalBatches; i++) {
        const batch = contacts.slice(i * BATCH_SIZE, (i + 1) * BATCH_SIZE);

        if (totalBatches > 1) {
          toast({
            title: `Enviando lote ${i + 1} de ${totalBatches}`,
            description: `${batch.length} contactos en este lote...`,
          });
        }

        const response = await apiRequest("POST", "/api/ghl/send-contacts", {
          contacts: batch,
          tags: [segmentTag],
          segmentId: selectedSegment.id,
        });
        const result = await response.json();

        aggregated.created += result.created || 0;
        aggregated.updated += result.updated || 0;
        aggregated.failed += result.failed || 0;
        if (result.errors) {
          aggregated.errors.push(...result.errors);
        }
      }

      setGhlSendResult(aggregated);

      if (aggregated.failed === 0) {
        toast({
          title: "Contactos enviados",
          description: `${aggregated.created + aggregated.updated} contactos sincronizados a GoHighLevel`,
        });
      } else {
        toast({
          title: "Envio parcial",
          description: `${aggregated.created + aggregated.updated} enviados, ${aggregated.failed} fallidos`,
          variant: "destructive",
        });
      }
    } catch (error: any) {
      toast({
        title: "Error",
        description: error.message || "No se pudieron enviar los contactos a GoHighLevel",
        variant: "destructive",
      });
    } finally {
      setIsSendingToGhl(false);
    }
  };

  const getDisplayColumns = (members: SegmentMember[]) => {
    if (!members || members.length === 0) return [];
    const firstMember = members[0];
    const priorityColumns = ['customer_id', 'email', 'name', 'status', 'amount', 'created'];
    const availableColumns = Object.keys(firstMember);
    const sortedColumns = [
      ...priorityColumns.filter(col => availableColumns.includes(col)),
      ...availableColumns.filter(col => !priorityColumns.includes(col))
    ];
    return sortedColumns.slice(0, 5);
  };

  const formatCellValue = (value: any): string => {
    if (value === null || value === undefined) return "-";
    if (typeof value === 'object') {
      if (value.value) return new Date(value.value).toLocaleDateString('es-ES');
      return JSON.stringify(value).slice(0, 30);
    }
    if (typeof value === 'number') return value.toLocaleString('es-ES');
    return String(value).slice(0, 50);
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Users className="h-6 w-6 text-primary" />
            Segmentacion de Clientes
          </h1>
          <p className="text-muted-foreground mt-1">
            Crea y gestiona segmentos de clientes para campanas de marketing personalizadas
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <ClientSelector
            selectedClientId={selectedClientId}
            onClientChange={setSelectedClientId}
          />
          <Button
            variant="outline"
            className="gap-2"
            onClick={() => generateAISegmentMutation.mutate()}
            disabled={generateAISegmentMutation.isPending}
            data-testid="button-ai-generate-segment"
          >
            {generateAISegmentMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            {generateAISegmentMutation.isPending ? "Generando..." : "AI Recomendar"}
          </Button>
          <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
            <DialogTrigger asChild>
              <Button className="gap-2" data-testid="button-create-segment">
                <Plus className="h-4 w-4" />
                Crear Segmento
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Crear Nuevo Segmento</DialogTitle>
                <DialogDescription>
                  Define un segmento de clientes basado en criterios especificos
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label htmlFor="name">Nombre del Segmento</Label>
                  <Input
                    id="name"
                    placeholder="ej. Clientes de Alto Valor Inactivos"
                    value={newSegmentName}
                    onChange={(e) => setNewSegmentName(e.target.value)}
                    data-testid="input-segment-name"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="description">Descripcion</Label>
                  <Textarea
                    id="description"
                    placeholder="Describe este segmento..."
                    value={newSegmentDescription}
                    onChange={(e) => setNewSegmentDescription(e.target.value)}
                    data-testid="input-segment-description"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Asignar a Cliente</Label>
                  <Select
                    value={selectedClientId?.toString() || "all"}
                    onValueChange={(v) => setSelectedClientId(v === "all" ? null : parseInt(v))}
                  >
                    <SelectTrigger data-testid="select-segment-client">
                      <SelectValue placeholder="Selecciona un cliente" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">Todos los Clientes</SelectItem>
                      {clients?.map((client) => (
                        <SelectItem key={client.id} value={client.id.toString()}>
                          {client.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setIsCreateDialogOpen(false)}>
                  Cancelar
                </Button>
                <Button
                  onClick={handleCreateSegment}
                  disabled={!newSegmentName.trim() || createSegmentMutation.isPending}
                  data-testid="button-save-segment"
                >
                  {createSegmentMutation.isPending ? "Creando..." : "Crear Segmento"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Buscar segmentos..."
            className="pl-9"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            data-testid="input-search-segments"
          />
        </div>
        <Button variant="outline" size="icon" data-testid="button-filter-segments">
          <Filter className="h-4 w-4" />
        </Button>
      </div>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[...Array(6)].map((_, i) => (
            <Card key={i}>
              <CardContent className="p-6">
                <Skeleton className="h-6 w-32 mb-2" />
                <Skeleton className="h-4 w-full mb-4" />
                <Skeleton className="h-8 w-24" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : !filteredSegments || filteredSegments.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <div className="h-16 w-16 rounded-full bg-muted flex items-center justify-center mb-4">
              <Target className="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-semibold mb-2">Sin Segmentos Aun</h3>
            <p className="text-sm text-muted-foreground text-center max-w-md mb-6">
              Crea segmentos de clientes para dirigirte a grupos especificos con campanas de marketing personalizadas.
              Puedes crear segmentos manualmente o dejar que la AI los recomiende basandose en tus datos.
            </p>
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                className="gap-2"
                onClick={() => generateAISegmentMutation.mutate()}
                disabled={generateAISegmentMutation.isPending}
              >
                {generateAISegmentMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                AI Recomendar
              </Button>
              <Button onClick={() => setIsCreateDialogOpen(true)} className="gap-2">
                <Plus className="h-4 w-4" />
                Crear Segmento
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredSegments.map((segment) => (
            <Card 
              key={segment.id} 
              className="hover-elevate transition-all cursor-pointer" 
              onClick={() => handleSegmentClick(segment)}
              data-testid={`segment-card-${segment.id}`}
            >
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
                      {segment.isAiGenerated ? (
                        <Sparkles className="h-5 w-5 text-primary" />
                      ) : (
                        <Users className="h-5 w-5 text-primary" />
                      )}
                    </div>
                    <div>
                      <CardTitle className="text-base">{segment.name}</CardTitle>
                      <div className="flex items-center gap-2 mt-1">
                        <Badge variant={segment.status === "active" ? "default" : "secondary"}>
                          {segment.status === "active" ? "activo" : segment.status}
                        </Badge>
                        {segment.isAiGenerated && (
                          <Badge variant="outline" className="gap-1">
                            <Zap className="h-3 w-3" />
                            AI
                          </Badge>
                        )}
                      </div>
                    </div>
                  </div>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                      <Button variant="ghost" size="icon" data-testid={`segment-menu-${segment.id}`}>
                        <MoreVertical className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem className="gap-2" onClick={() => handleSegmentClick(segment)}>
                        <Eye className="h-4 w-4" />
                        Ver Detalles
                      </DropdownMenuItem>
                      <DropdownMenuItem className="gap-2" onClick={(e) => {
                        e.stopPropagation();
                        handleExportToGhl(segment);
                      }}>
                        <Send className="h-4 w-4" />
                        Exportar a CRM
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem 
                        className="gap-2 text-destructive"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteSegment(segment.id);
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                        Eliminar
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground mb-4 line-clamp-2">
                  {segment.description || "Sin descripcion"}
                </p>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Users className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm font-medium">
                      {segment.contactCount?.toLocaleString() || 0} contactos
                    </span>
                  </div>
                  {segment.lastSyncedAt && (
                    <div className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Calendar className="h-3 w-3" />
                      Sincronizado {new Date(segment.lastSyncedAt).toLocaleDateString('es-ES')}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={isDetailDialogOpen} onOpenChange={setIsDetailDialogOpen}>
        <DialogContent className="max-w-4xl max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
                  {selectedSegment?.isAiGenerated ? (
                    <Sparkles className="h-5 w-5 text-primary" />
                  ) : (
                    <Users className="h-5 w-5 text-primary" />
                  )}
                </div>
                <div>
                  <DialogTitle>{selectedSegment?.name}</DialogTitle>
                  <DialogDescription className="mt-1">
                    {selectedSegment?.description || "Sin descripcion"}
                  </DialogDescription>
                </div>
              </div>
            </div>
          </DialogHeader>

          <div className="flex items-center gap-2 py-2">
            <Badge variant={selectedSegment?.status === "active" ? "default" : "secondary"}>
              {selectedSegment?.status === "active" ? "activo" : selectedSegment?.status}
            </Badge>
            {selectedSegment?.isAiGenerated && (
              <Badge variant="outline" className="gap-1">
                <Zap className="h-3 w-3" />
                Generado por AI
              </Badge>
            )}
            <Badge variant="secondary" className="gap-1">
              <Users className="h-3 w-3" />
              {selectedSegment?.contactCount?.toLocaleString() || 0} contactos
            </Badge>
          </div>

          {selectedSegment?.isAiGenerated && (
            <div className="border rounded-md p-4 bg-muted/30 space-y-2">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                <h4 className="font-medium text-sm">Logica de Segmentacion</h4>
              </div>
              <p className="text-sm text-muted-foreground">
                {(selectedSegment.criteria as SegmentCriteria)?.explanation || "Este segmento fue generado automaticamente por inteligencia artificial basandose en los patrones encontrados en tus datos de BigQuery."}
              </p>
              {(selectedSegment.criteria as SegmentCriteria)?.confidence && (
                <div className="flex items-center gap-2 mt-2">
                  <span className="text-xs text-muted-foreground">Confianza:</span>
                  <Badge variant="outline" className="text-xs">
                    {Math.round(((selectedSegment.criteria as SegmentCriteria)?.confidence || 0) * 100)}%
                  </Badge>
                </div>
              )}
            </div>
          )}

          <div className="flex-1 overflow-auto border rounded-md">
            <div className="p-3 border-b bg-muted/50 flex items-center justify-between">
              <h4 className="font-medium text-sm">Lista de Clientes del Segmento</h4>
              <Button 
                variant="ghost" 
                size="sm" 
                onClick={() => refetchMembers()}
                disabled={isLoadingMembers}
                className="gap-1"
              >
                <RefreshCw className={`h-3 w-3 ${isLoadingMembers ? 'animate-spin' : ''}`} />
                Actualizar
              </Button>
            </div>
            
            {isLoadingMembers ? (
              <div className="p-8 flex flex-col items-center justify-center text-muted-foreground">
                <Loader2 className="h-8 w-8 animate-spin mb-2" />
                <p className="text-sm">Cargando clientes del segmento...</p>
              </div>
            ) : segmentMembers?.members && segmentMembers.members.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    {getDisplayColumns(segmentMembers.members).map((col) => (
                      <TableHead key={col} className="capitalize">
                        {col.replace(/_/g, ' ')}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {segmentMembers.members.slice(0, 100).map((member, idx) => (
                    <TableRow key={member.customer_id || idx}>
                      {getDisplayColumns(segmentMembers.members).map((col) => (
                        <TableCell key={col} className="text-sm">
                          {formatCellValue(member[col])}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 flex flex-col items-center justify-center text-muted-foreground">
                <Users className="h-8 w-8 mb-2 opacity-50" />
                <p className="text-sm text-center">
                  {segmentMembers?.message || "No hay datos de clientes disponibles para este segmento"}
                </p>
                {selectedSegment?.isAiGenerated ? (
                  <div className="text-center mt-2">
                    <p className="text-xs">
                      Haz clic en "Actualizar" para obtener la lista de clientes desde BigQuery
                    </p>
                    <Button 
                      variant="outline" 
                      size="sm" 
                      onClick={() => refetchMembers()}
                      disabled={isLoadingMembers}
                      className="mt-3 gap-1"
                    >
                      <RefreshCw className={`h-3 w-3 ${isLoadingMembers ? 'animate-spin' : ''}`} />
                      Cargar Clientes
                    </Button>
                  </div>
                ) : (
                  <p className="text-xs mt-1">
                    Los segmentos creados manualmente no tienen lista de clientes automatica
                  </p>
                )}
              </div>
            )}
          </div>

          {segmentMembers?.members && segmentMembers.members.length > 100 && (
            <p className="text-xs text-muted-foreground text-center py-2">
              Mostrando 100 de {segmentMembers.count.toLocaleString()} clientes
            </p>
          )}

          <DialogFooter className="gap-2 sm:gap-0">
            <Button 
              variant="destructive" 
              onClick={() => selectedSegment && handleDeleteSegment(selectedSegment.id)}
              disabled={deleteSegmentMutation.isPending}
              className="gap-2"
            >
              <Trash2 className="h-4 w-4" />
              Eliminar
            </Button>
            <Button 
              variant="outline" 
              className="gap-2" 
              data-testid="button-export-segment"
              onClick={() => {
                if (selectedSegment) {
                  setIsDetailDialogOpen(false);
                  handleExportToGhl(selectedSegment);
                }
              }}
            >
              <Send className="h-4 w-4" />
              Exportar a CRM
            </Button>
            <Button variant="outline" onClick={() => setIsDetailDialogOpen(false)}>
              Cerrar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={isExportDialogOpen} onOpenChange={(open) => {
        if (!isSendingToGhl) setIsExportDialogOpen(open);
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Exportar Segmento a GoHighLevel</DialogTitle>
            <DialogDescription>
              {ghlSendResult 
                ? "Resultado del envio de contactos"
                : `Enviar los contactos del segmento "${selectedSegment?.name}" a GoHighLevel CRM`
              }
            </DialogDescription>
          </DialogHeader>

          {ghlSendResult ? (
            <div className="space-y-4 py-4">
              <div className="grid grid-cols-3 gap-4">
                <div className="text-center p-3 border rounded-md bg-muted/30">
                  <p className="text-2xl font-bold text-green-500">{ghlSendResult.created}</p>
                  <p className="text-xs text-muted-foreground">Creados</p>
                </div>
                <div className="text-center p-3 border rounded-md bg-muted/30">
                  <p className="text-2xl font-bold text-blue-500">{ghlSendResult.updated}</p>
                  <p className="text-xs text-muted-foreground">Actualizados</p>
                </div>
                <div className="text-center p-3 border rounded-md bg-muted/30">
                  <p className="text-2xl font-bold text-red-500">{ghlSendResult.failed}</p>
                  <p className="text-xs text-muted-foreground">Fallidos</p>
                </div>
              </div>
              {ghlSendResult.errors.length > 0 && (
                <div className="border rounded-md p-3 bg-destructive/10">
                  <p className="text-sm font-medium mb-1">Errores:</p>
                  {ghlSendResult.errors.slice(0, 5).map((err, i) => (
                    <p key={i} className="text-xs text-muted-foreground">{err}</p>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-4 py-4">
              <div className="flex items-center gap-3 p-3 border rounded-md bg-muted/30">
                <Users className="h-5 w-5 text-primary" />
                <div>
                  <p className="text-sm font-medium">{selectedSegment?.contactCount?.toLocaleString() || 0} contactos</p>
                  <p className="text-xs text-muted-foreground">Se enviaran a GoHighLevel</p>
                </div>
              </div>
              <div className="flex items-center gap-3 p-3 border rounded-md bg-muted/30">
                <Target className="h-5 w-5 text-primary" />
                <div>
                  <p className="text-sm font-medium">Tag: "{selectedSegment?.name}"</p>
                  <p className="text-xs text-muted-foreground">Se aplicara automaticamente a todos los contactos</p>
                </div>
              </div>
            </div>
          )}

          <DialogFooter>
            {ghlSendResult ? (
              <Button onClick={() => setIsExportDialogOpen(false)}>
                Cerrar
              </Button>
            ) : (
              <>
                <Button variant="outline" onClick={() => setIsExportDialogOpen(false)} disabled={isSendingToGhl}>
                  Cancelar
                </Button>
                <Button 
                  className="gap-2" 
                  onClick={handleConfirmSendToGhl}
                  disabled={isSendingToGhl}
                  data-testid="button-confirm-export-ghl"
                >
                  {isSendingToGhl ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )}
                  {isSendingToGhl ? "Enviando..." : "Confirmar Envio"}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
