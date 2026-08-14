import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useRoute } from "wouter";
import { queryClient, apiRequest } from "@/lib/queryClient";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { PageVersion, PageDesign } from "@shared/schema";
import {
  ArrowLeft,
  Loader2,
  Smartphone,
  Tablet,
  Monitor,
  Eye,
  Save,
  Layers,
  Palette,
  LayoutGrid,
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { Link } from "wouter";
import { GrapesEditor } from "@/components/page-builder/grapes-editor";

type ViewMode = "desktop" | "tablet" | "mobile";
type PanelTab = "blocks" | "layers" | "styles";

interface VersionContent {
  htmlContent?: string;
  cssContent?: string;
  gjsComponents?: any;
  gjsStyles?: any;
}

export default function PageBuilder() {
  const [, params] = useRoute("/page-builder/:pageId");
  const pageId = params?.pageId ? parseInt(params.pageId) : null;
  const { toast } = useToast();

  const [activeVersionId, setActiveVersionId] = useState<number | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("desktop");
  const [activePanel, setActivePanel] = useState<PanelTab>("blocks");
  const [hasChanges, setHasChanges] = useState(false);
  const [editorReady, setEditorReady] = useState(false);
  
  const pendingDataRef = useRef<{ html: string; css: string; components: any; styles: any } | null>(null);
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const { data: page, isLoading: pageLoading } = useQuery<PageDesign>({
    queryKey: ["/api/pages", pageId],
    enabled: !!pageId,
  });

  const { data: versions = [] } = useQuery<PageVersion[]>({
    queryKey: ["/api/pages", pageId, "versions"],
    enabled: !!pageId,
  });

  const activeVersion = versions.find((v) => v.isActive) || versions[0];

  useEffect(() => {
    if (activeVersion && !activeVersionId) {
      setActiveVersionId(activeVersion.id);
    }
  }, [activeVersion, activeVersionId]);

  const updateVersionMutation = useMutation({
    mutationFn: async (data: { html: string; css: string; components: any; styles: any }) => {
      return apiRequest("PUT", `/api/versions/${activeVersionId}`, {
        htmlContent: data.html,
        cssContent: data.css,
        gjsComponents: data.components,
        gjsStyles: data.styles,
      });
    },
    onSuccess: () => {
      setHasChanges(false);
      queryClient.invalidateQueries({ queryKey: ["/api/pages", pageId, "versions"] });
      toast({ title: "Guardado", description: "Los cambios se guardaron correctamente" });
    },
    onError: () => {
      toast({ title: "Error", description: "No se pudieron guardar los cambios", variant: "destructive" });
    },
  });

  const handleEditorSave = useCallback((data: { html: string; css: string; components: any; styles: any }) => {
    pendingDataRef.current = data;
    setHasChanges(true);

    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }

    saveTimeoutRef.current = setTimeout(() => {
      if (pendingDataRef.current && activeVersionId) {
        updateVersionMutation.mutate(pendingDataRef.current);
      }
    }, 3000);
  }, [activeVersionId]);

  const handleManualSave = () => {
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }
    if (pendingDataRef.current) {
      updateVersionMutation.mutate(pendingDataRef.current);
    }
  };

  const handlePreview = () => {
    const content = pendingDataRef.current || initialContent;
    if (content && (content.html || content.components)) {
      const previewHtml = `
        <!DOCTYPE html>
        <html lang="es">
        <head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>${page?.name || 'Preview'}</title>
          <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
          <style>${content.css || ''}</style>
        </head>
        <body style="margin: 0; background: #0f172a;">
          ${content.html || ''}
        </body>
        </html>
      `;
      const blob = new Blob([previewHtml], { type: 'text/html' });
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
    }
  };

  const initialContent = activeVersion ? {
    html: (activeVersion as VersionContent).htmlContent || '',
    css: (activeVersion as VersionContent).cssContent || '',
    components: (activeVersion as VersionContent).gjsComponents,
    styles: (activeVersion as VersionContent).gjsStyles,
  } : undefined;

  if (pageLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!page) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <p className="text-muted-foreground">Pagina no encontrada</p>
        <Link href="/dynamic-persona">
          <Button variant="outline">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Volver
          </Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-[#1a1a2e]">
      <header className="flex items-center justify-between gap-4 px-4 py-2 border-b border-slate-700 bg-[#1e293b]">
        <div className="flex items-center gap-3">
          <Link href="/dynamic-persona">
            <Button variant="ghost" size="icon" className="text-slate-300 hover:text-white" data-testid="button-back">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <h1 className="font-semibold text-white">{page.name}</h1>
            <p className="text-xs text-slate-400">/{page.slug}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex items-center border border-slate-600 rounded-md bg-slate-800">
            <Button
              variant="ghost"
              size="icon"
              className={viewMode === "mobile" ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"}
              onClick={() => setViewMode("mobile")}
              data-testid="button-view-mobile"
            >
              <Smartphone className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className={viewMode === "tablet" ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"}
              onClick={() => setViewMode("tablet")}
              data-testid="button-view-tablet"
            >
              <Tablet className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className={viewMode === "desktop" ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"}
              onClick={() => setViewMode("desktop")}
              data-testid="button-view-desktop"
            >
              <Monitor className="h-4 w-4" />
            </Button>
          </div>

          <Separator orientation="vertical" className="h-6 bg-slate-600" />

          <Button
            variant="ghost"
            size="sm"
            className="text-slate-300 hover:text-white"
            onClick={handlePreview}
            data-testid="button-preview"
          >
            <Eye className="mr-2 h-4 w-4" />
            Vista Previa
          </Button>

          <Button
            size="sm"
            onClick={handleManualSave}
            disabled={!hasChanges || updateVersionMutation.isPending}
            data-testid="button-save"
          >
            {updateVersionMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            Guardar
          </Button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-72 border-r border-slate-700 bg-[#1e293b] flex flex-col">
          <Tabs value={activePanel} onValueChange={(v) => setActivePanel(v as PanelTab)} className="flex flex-col h-full">
            <TabsList className="grid grid-cols-3 m-2 bg-slate-800">
              <TabsTrigger value="blocks" className="text-xs data-[state=active]:bg-primary data-[state=active]:text-white">
                <LayoutGrid className="h-4 w-4 mr-1" />
                Bloques
              </TabsTrigger>
              <TabsTrigger value="layers" className="text-xs data-[state=active]:bg-primary data-[state=active]:text-white">
                <Layers className="h-4 w-4 mr-1" />
                Capas
              </TabsTrigger>
              <TabsTrigger value="styles" className="text-xs data-[state=active]:bg-primary data-[state=active]:text-white">
                <Palette className="h-4 w-4 mr-1" />
                Estilos
              </TabsTrigger>
            </TabsList>

            <ScrollArea className="flex-1">
              <div 
                id="blocks-container" 
                className={activePanel === "blocks" ? "p-2" : "hidden"} 
              />
              <div 
                id="layers-container" 
                className={activePanel === "layers" ? "p-2" : "hidden"} 
              />
              <div 
                id="styles-container" 
                className={activePanel === "styles" ? "p-2" : "hidden"} 
              />
            </ScrollArea>
          </Tabs>
        </aside>

        <main className="flex-1 overflow-hidden">
          {activeVersionId && (
            <GrapesEditor
              key={activeVersionId}
              initialContent={initialContent}
              onSave={handleEditorSave}
              onLoad={() => setEditorReady(true)}
            />
          )}
        </main>
      </div>
    </div>
  );
}
