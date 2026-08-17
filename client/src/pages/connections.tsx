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
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { apiRequest, queryClient } from "@/lib/queryClient";
import {
  Database,
  Plus,
  Check,
  X,
  AlertCircle,
  RefreshCw,
  Trash2,
  Edit2,
  Play,
  Eye,
  EyeOff,
  Building2,
  Link2,
  Unlink,
  ShieldCheck,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MoreVertical } from "lucide-react";
import type { BigQueryConnection, Client } from "@shared/schema";

export default function Connections() {
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [isLinkDialogOpen, setIsLinkDialogOpen] = useState(false);
  const [selectedConnectionId, setSelectedConnectionId] = useState<number | null>(null);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState("");
  const [credentials, setCredentials] = useState("");
  const [showCredentials, setShowCredentials] = useState(false);

  const { data: connections, isLoading } = useQuery<BigQueryConnection[]>({
    queryKey: ["/api/connections"],
  });

  const { data: clients } = useQuery<Client[]>({
    queryKey: ["/api/clients"],
  });

  // Get clients linked to a specific connection
  const getLinkedClients = (connectionId: number) => {
    return clients?.filter(c => c.connectionId === connectionId) || [];
  };

  // Get unlinked clients (no connection or different connection)
  const getUnlinkedClients = () => {
    return clients?.filter(c => !c.connectionId) || [];
  };

  const addConnectionMutation = useMutation({
    mutationFn: async () => {
      const response = await apiRequest("POST", "/api/connections", {
        name,
        projectId,
        credentials,
      });
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/connections"] });
      setIsAddDialogOpen(false);
      resetForm();
    },
  });

  const testConnectionMutation = useMutation({
    mutationFn: async (connectionId: number) => {
      const response = await apiRequest("POST", `/api/connections/${connectionId}/test`, {});
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/connections"] });
    },
  });

  const deleteConnectionMutation = useMutation({
    mutationFn: async (connectionId: number) => {
      await apiRequest("DELETE", `/api/connections/${connectionId}`, {});
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/connections"] });
      queryClient.invalidateQueries({ queryKey: ["/api/clients"] });
    },
  });

  const linkClientMutation = useMutation({
    mutationFn: async ({ clientId, connectionId }: { clientId: number; connectionId: number | null }) => {
      const response = await apiRequest("PATCH", `/api/clients/${clientId}`, {
        connectionId,
      });
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/clients"] });
      setIsLinkDialogOpen(false);
      setSelectedClientId("");
      setSelectedConnectionId(null);
    },
  });

  const handleLinkClient = () => {
    if (selectedClientId && selectedConnectionId) {
      linkClientMutation.mutate({
        clientId: parseInt(selectedClientId),
        connectionId: selectedConnectionId,
      });
    }
  };

  const handleUnlinkClient = (clientId: number) => {
    linkClientMutation.mutate({
      clientId,
      connectionId: null,
    });
  };

  const openLinkDialog = (connectionId: number) => {
    setSelectedConnectionId(connectionId);
    setSelectedClientId("");
    setIsLinkDialogOpen(true);
  };

  const resetForm = () => {
    setName("");
    setProjectId("");
    setCredentials("");
  };

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Database className="h-6 w-6 text-primary" />
            BigQuery Connections
          </h1>
          <p className="text-muted-foreground mt-1">
            Manage your data warehouse connections
          </p>
        </div>
        <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
          <DialogTrigger asChild>
            <Button className="gap-2" data-testid="button-add-connection">
              <Plus className="h-4 w-4" />
              Add Connection
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>Add BigQuery Connection</DialogTitle>
              <DialogDescription>
                Connect to a Google BigQuery project to query your retail data.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="name">Connection Name</Label>
                <Input
                  id="name"
                  placeholder="e.g., Production Warehouse"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  data-testid="input-connection-name"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="projectId">Project ID</Label>
                <Input
                  id="projectId"
                  placeholder="my-project-123"
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                  data-testid="input-project-id"
                />
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="credentials">Service Account JSON</Label>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowCredentials(!showCredentials)}
                    className="gap-1"
                  >
                    {showCredentials ? (
                      <>
                        <EyeOff className="h-3 w-3" />
                        Hide
                      </>
                    ) : (
                      <>
                        <Eye className="h-3 w-3" />
                        Show
                      </>
                    )}
                  </Button>
                </div>
                <Textarea
                  id="credentials"
                  placeholder='Paste your service account JSON key here...'
                  className={`min-h-[120px] font-mono text-xs ${!showCredentials ? "blur-sm hover:blur-none focus:blur-none" : ""}`}
                  value={credentials}
                  onChange={(e) => setCredentials(e.target.value)}
                  data-testid="input-credentials"
                />
                <p className="text-xs text-muted-foreground">
                  This will be encrypted and stored securely. Never shared or logged.
                </p>
              </div>
              <Alert>
                <ShieldCheck className="h-4 w-4" />
                <AlertDescription>
                  <p className="mb-1.5">The service account above needs these IAM roles granted on the BigQuery project:</p>
                  <ul className="space-y-0.5 font-mono text-xs">
                    <li>roles/mcp.toolUser</li>
                    <li>roles/bigquery.jobUser</li>
                    <li>roles/bigquery.dataViewer</li>
                  </ul>
                </AlertDescription>
              </Alert>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setIsAddDialogOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => addConnectionMutation.mutate()}
                disabled={!name || !projectId || !credentials || addConnectionMutation.isPending}
                data-testid="button-save-connection"
              >
                {addConnectionMutation.isPending ? "Adding..." : "Add Connection"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[...Array(2)].map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : !connections || connections.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <div className="h-16 w-16 rounded-full bg-muted flex items-center justify-center mb-4">
              <Database className="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-semibold mb-2">No Connections</h3>
            <p className="text-sm text-muted-foreground text-center max-w-md mb-6">
              Connect to Google BigQuery to start querying your retail data warehouse.
              You'll need a service account with BigQuery access.
            </p>
            <Button onClick={() => setIsAddDialogOpen(true)} className="gap-2">
              <Plus className="h-4 w-4" />
              Add First Connection
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {connections.map((connection) => (
            <Card key={connection.id} className="hover-elevate transition-all" data-testid={`connection-card-${connection.id}`}>
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-4">
                    <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center">
                      <Database className="h-6 w-6 text-primary" />
                    </div>
                    <div>
                      <CardTitle className="text-lg">{connection.name}</CardTitle>
                      <div className="flex items-center gap-2 mt-1">
                        <code className="text-xs bg-muted px-2 py-0.5 rounded">
                          {connection.projectId}
                        </code>
                        {connection.datasetId && (
                          <code className="text-xs bg-muted px-2 py-0.5 rounded">
                            {connection.datasetId}
                          </code>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={connection.isActive ? "default" : "secondary"}>
                      {connection.isActive ? (
                        <>
                          <Check className="h-3 w-3 mr-1" />
                          Connected
                        </>
                      ) : (
                        <>
                          <AlertCircle className="h-3 w-3 mr-1" />
                          Inactive
                        </>
                      )}
                    </Badge>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" data-testid={`connection-menu-${connection.id}`}>
                          <MoreVertical className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          className="gap-2"
                          onClick={() => testConnectionMutation.mutate(connection.id)}
                        >
                          <Play className="h-4 w-4" />
                          Test Connection
                        </DropdownMenuItem>
                        <DropdownMenuItem className="gap-2">
                          <Edit2 className="h-4 w-4" />
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          className="gap-2 text-destructive"
                          onClick={() => deleteConnectionMutation.mutate(connection.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-6 text-sm text-muted-foreground">
                  {connection.lastTestedAt && (
                    <span className="flex items-center gap-1">
                      <RefreshCw className="h-3 w-3" />
                      Last tested: {new Date(connection.lastTestedAt).toLocaleString()}
                    </span>
                  )}
                  <span className="flex items-center gap-1">
                    Added: {new Date(connection.createdAt).toLocaleDateString()}
                  </span>
                </div>

                {/* Linked Clients Section */}
                <div className="border-t pt-4">
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-sm font-medium flex items-center gap-2">
                      <Building2 className="h-4 w-4 text-muted-foreground" />
                      Clientes Vinculados
                    </h4>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => openLinkDialog(connection.id)}
                      className="gap-1"
                      disabled={getUnlinkedClients().length === 0}
                      data-testid={`button-link-client-${connection.id}`}
                    >
                      <Link2 className="h-3 w-3" />
                      Vincular Cliente
                    </Button>
                  </div>
                  
                  {getLinkedClients(connection.id).length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      No hay clientes vinculados a esta conexion.
                    </p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {getLinkedClients(connection.id).map((client) => (
                        <Badge
                          key={client.id}
                          variant="secondary"
                          className="gap-1 pl-2 pr-0.5 flex items-center"
                          data-testid={`linked-client-${client.id}`}
                        >
                          <span
                            className="w-2 h-2 rounded-full shrink-0"
                            style={{ backgroundColor: client.primaryColor || "#3B82F6" }}
                          />
                          <span>{client.name}</span>
                          <button
                            type="button"
                            className="ml-1 p-0.5 rounded-sm opacity-70 hover:opacity-100 transition-opacity"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleUnlinkClient(client.id);
                            }}
                            data-testid={`button-unlink-client-${client.id}`}
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Link Client Dialog */}
      <Dialog open={isLinkDialogOpen} onOpenChange={setIsLinkDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Vincular Cliente</DialogTitle>
            <DialogDescription>
              Selecciona un cliente para vincularlo a esta conexion BigQuery.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Label htmlFor="client-select">Cliente</Label>
            <Select value={selectedClientId} onValueChange={setSelectedClientId}>
              <SelectTrigger className="mt-2" data-testid="select-client">
                <SelectValue placeholder="Seleccionar cliente..." />
              </SelectTrigger>
              <SelectContent>
                {getUnlinkedClients().map((client) => (
                  <SelectItem key={client.id} value={client.id.toString()}>
                    <div className="flex items-center gap-2">
                      <span
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: client.primaryColor || "#3B82F6" }}
                      />
                      {client.name}
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {getUnlinkedClients().length === 0 && (
              <p className="text-sm text-muted-foreground mt-2">
                Todos los clientes ya estan vinculados a una conexion.
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsLinkDialogOpen(false)}>
              Cancelar
            </Button>
            <Button
              onClick={handleLinkClient}
              disabled={!selectedClientId || linkClientMutation.isPending}
              data-testid="button-confirm-link"
            >
              {linkClientMutation.isPending ? "Vinculando..." : "Vincular"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
