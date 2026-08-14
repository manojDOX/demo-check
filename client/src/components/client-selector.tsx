import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Building2, Plus, Loader2 } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { apiRequest, queryClient } from "@/lib/queryClient";
import type { Client, BigQueryConnection } from "@shared/schema";

const addClientSchema = z.object({
  name: z.string().min(1, "Client name is required").max(100, "Name too long"),
  industry: z.string().default("retail"),
  primaryColor: z.string().regex(/^#[0-9A-Fa-f]{6}$/, "Invalid color format").default("#3B82F6"),
  connectionId: z.number().nullable().optional(),
});

type AddClientFormData = z.infer<typeof addClientSchema>;

const industryOptions = [
  { value: "retail", label: "Retail" },
  { value: "ecommerce", label: "E-Commerce" },
  { value: "fashion", label: "Fashion" },
  { value: "electronics", label: "Electronics" },
  { value: "food_beverage", label: "Food & Beverage" },
  { value: "health_beauty", label: "Health & Beauty" },
  { value: "home_garden", label: "Home & Garden" },
  { value: "sports", label: "Sports & Outdoors" },
  { value: "other", label: "Other" },
];

const colorOptions = [
  { value: "#3B82F6", label: "Blue" },
  { value: "#10B981", label: "Green" },
  { value: "#8B5CF6", label: "Purple" },
  { value: "#F59E0B", label: "Amber" },
  { value: "#EF4444", label: "Red" },
  { value: "#EC4899", label: "Pink" },
  { value: "#06B6D4", label: "Cyan" },
  { value: "#6366F1", label: "Indigo" },
];

interface ClientSelectorProps {
  selectedClientId: number | null;
  onClientChange: (clientId: number | null) => void;
  clients?: Client[];
  isLoadingClients?: boolean;
}

function AddClientDialog({ onClientAdded }: { onClientAdded?: (client: Client) => void }) {
  const [open, setOpen] = useState(false);
  const { toast } = useToast();

  const { data: connections } = useQuery<BigQueryConnection[]>({
    queryKey: ["/api/connections"],
  });

  const form = useForm<AddClientFormData>({
    resolver: zodResolver(addClientSchema),
    defaultValues: {
      name: "",
      industry: "retail",
      primaryColor: "#3B82F6",
      connectionId: null,
    },
  });

  const createClientMutation = useMutation({
    mutationFn: async (data: AddClientFormData) => {
      const response = await apiRequest("POST", "/api/clients", data);
      return response.json();
    },
    onSuccess: (newClient: Client) => {
      queryClient.invalidateQueries({ queryKey: ["/api/clients"] });
      toast({
        title: "Client created",
        description: `${newClient.name} has been added successfully.`,
      });
      form.reset();
      setOpen(false);
      onClientAdded?.(newClient);
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to create client",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const onSubmit = (data: AddClientFormData) => {
    createClientMutation.mutate(data);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="icon" className="h-9 w-9 shrink-0" data-testid="button-add-client" title="Add Client">
          <Plus className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add New Client</DialogTitle>
          <DialogDescription>
            Create a new retail client to track their analytics and KPIs.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Client Name</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g., Acme Retail Store"
                      data-testid="input-client-name"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="industry"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Industry</FormLabel>
                  <Select onValueChange={field.onChange} defaultValue={field.value}>
                    <FormControl>
                      <SelectTrigger data-testid="select-industry">
                        <SelectValue placeholder="Select industry" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {industryOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value} data-testid={`select-industry-${option.value}`}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="primaryColor"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Brand Color</FormLabel>
                  <div className="flex flex-wrap gap-2">
                    {colorOptions.map((color) => (
                      <button
                        key={color.value}
                        type="button"
                        onClick={() => field.onChange(color.value)}
                        className={`h-8 w-8 rounded-md border-2 transition-all ${
                          field.value === color.value
                            ? "border-foreground scale-110"
                            : "border-transparent hover:scale-105"
                        }`}
                        style={{ backgroundColor: color.value }}
                        title={color.label}
                        data-testid={`button-color-${color.value.slice(1)}`}
                      />
                    ))}
                  </div>
                  <FormMessage />
                </FormItem>
              )}
            />

            {connections && connections.length > 0 && (
              <FormField
                control={form.control}
                name="connectionId"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>BigQuery Connection (Optional)</FormLabel>
                    <Select
                      onValueChange={(value) => field.onChange(value === "none" ? null : parseInt(value))}
                      defaultValue={field.value?.toString() || "none"}
                    >
                      <FormControl>
                        <SelectTrigger data-testid="select-connection">
                          <SelectValue placeholder="Select connection" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="none" data-testid="select-connection-none">No connection</SelectItem>
                        {connections.map((conn) => (
                          <SelectItem key={conn.id} value={conn.id.toString()} data-testid={`select-connection-${conn.id}`}>
                            {conn.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <DialogFooter className="gap-2 pt-4">
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
                data-testid="button-cancel"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={createClientMutation.isPending}
                data-testid="button-submit-client"
              >
                {createClientMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Creating...
                  </>
                ) : (
                  "Create Client"
                )}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}

export function ClientSelector({ selectedClientId, onClientChange, clients: externalClients, isLoadingClients }: ClientSelectorProps) {
  // Use external clients if provided, otherwise query
  const { data: queriedClients, isLoading: isQueryLoading } = useQuery<Client[]>({
    queryKey: ["/api/clients"],
    enabled: !externalClients, // Only query if clients not passed
  });

  const clients = externalClients || queriedClients;
  const isLoading = isLoadingClients ?? isQueryLoading;

  if (isLoading) {
    return <Skeleton className="h-9 w-48" />;
  }

  if (!clients || clients.length === 0) {
    return <AddClientDialog onClientAdded={(client) => onClientChange(client.id)} />;
  }

  // Ensure we have a valid selectedClientId
  const selectedClient = clients.find(c => c.id === selectedClientId);
  const displayValue = selectedClient ? selectedClientId!.toString() : clients[0].id.toString();

  return (
    <div className="flex items-center gap-2">
      <Select
        value={displayValue}
        onValueChange={(value) => onClientChange(parseInt(value))}
      >
        <SelectTrigger className="w-48" data-testid="select-client">
          <Building2 className="mr-2 h-4 w-4 text-muted-foreground" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {clients.map((client) => (
            <SelectItem key={client.id} value={client.id.toString()} data-testid={`select-client-${client.id}`}>
              <div className="flex items-center gap-2">
                <div
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: client.primaryColor || "#3B82F6" }}
                />
                {client.name}
              </div>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <AddClientDialog />
    </div>
  );
}

export { AddClientDialog };
