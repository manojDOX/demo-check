import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { queryClient, apiRequest } from "@/lib/queryClient";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import type { PageDesign } from "@shared/schema";
import { Plus, FileEdit, Trash2, ExternalLink, Loader2 } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { Link } from "wouter";

export default function DynamicPersona() {
  const { toast } = useToast();
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newPageName, setNewPageName] = useState("");
  const [newPageSlug, setNewPageSlug] = useState("");

  const { data: pages = [], isLoading } = useQuery<PageDesign[]>({
    queryKey: ["/api/pages"],
  });

  const createPageMutation = useMutation({
    mutationFn: async (data: { name: string; slug: string }) => {
      return apiRequest("POST", "/api/pages", data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/pages"] });
      setIsCreateOpen(false);
      setNewPageName("");
      setNewPageSlug("");
      toast({ title: "Pagina creada", description: "La pagina se creo correctamente" });
    },
    onError: () => {
      toast({ title: "Error", description: "No se pudo crear la pagina", variant: "destructive" });
    },
  });

  const deletePageMutation = useMutation({
    mutationFn: async (id: number) => {
      return apiRequest("DELETE", `/api/pages/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/pages"] });
      toast({ title: "Pagina eliminada" });
    },
    onError: () => {
      toast({ title: "Error", description: "No se pudo eliminar la pagina", variant: "destructive" });
    },
  });

  const handleCreatePage = () => {
    if (!newPageName.trim()) return;
    createPageMutation.mutate({
      name: newPageName.trim(),
      slug: newPageSlug.trim() || newPageName.toLowerCase().replace(/\s+/g, "-"),
    });
  };

  const handleNameChange = (value: string) => {
    setNewPageName(value);
    if (!newPageSlug || newPageSlug === newPageName.toLowerCase().replace(/\s+/g, "-")) {
      setNewPageSlug(value.toLowerCase().replace(/\s+/g, "-"));
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold">Dynamic Persona</h1>
          <p className="text-muted-foreground mt-1">
            Crea y administra tus paginas personalizadas
          </p>
        </div>
        <Button onClick={() => setIsCreateOpen(true)} data-testid="button-create-page">
          <Plus className="mr-2 h-4 w-4" />
          Nueva Pagina
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : pages.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16">
            <FileEdit className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="text-lg font-semibold mb-2">No tienes paginas todavia</h3>
            <p className="text-muted-foreground text-center mb-4">
              Crea tu primera pagina para comenzar a construir tu sitio web
            </p>
            <Button onClick={() => setIsCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Crear Primera Pagina
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {pages.map((page) => (
            <Card key={page.id} className="hover-elevate" data-testid={`page-card-${page.id}`}>
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <CardTitle className="text-lg truncate">{page.name}</CardTitle>
                    <CardDescription className="mt-1">/{page.slug}</CardDescription>
                  </div>
                  <Badge variant={page.isPublished ? "default" : "secondary"}>
                    {page.isPublished ? "Publicada" : "Borrador"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-2">
                  <Link href={`/page-builder/${page.id}`} className="flex-1">
                    <Button variant="default" className="w-full" data-testid={`button-edit-page-${page.id}`}>
                      <FileEdit className="mr-2 h-4 w-4" />
                      Editar
                    </Button>
                  </Link>
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => deletePageMutation.mutate(page.id)}
                    disabled={deletePageMutation.isPending}
                    data-testid={`button-delete-page-${page.id}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                  {page.isPublished && (
                    <Button variant="outline" size="icon">
                      <ExternalLink className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Crear Nueva Pagina</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="pageName">Nombre de la Pagina</Label>
              <Input
                id="pageName"
                placeholder="Mi Pagina Principal"
                value={newPageName}
                onChange={(e) => handleNameChange(e.target.value)}
                data-testid="input-page-name"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="pageSlug">URL Slug</Label>
              <div className="flex items-center">
                <span className="text-muted-foreground mr-1">/</span>
                <Input
                  id="pageSlug"
                  placeholder="mi-pagina-principal"
                  value={newPageSlug}
                  onChange={(e) => setNewPageSlug(e.target.value)}
                  data-testid="input-page-slug"
                />
              </div>
              <p className="text-xs text-muted-foreground">
                Este sera el enlace de tu pagina
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)}>
              Cancelar
            </Button>
            <Button
              onClick={handleCreatePage}
              disabled={!newPageName.trim() || createPageMutation.isPending}
              data-testid="button-confirm-create"
            >
              {createPageMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Crear Pagina
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
