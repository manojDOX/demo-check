import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { ClientSelector } from "@/components/client-selector";
import type { Client } from "@shared/schema";
import {
  Building2,
  Save,
  Loader2,
  Package,
  Plus,
  Trash2,
  Pencil,
  Target,
  FileText,
  Info,
  DollarSign,
  Tag,
  Sparkles,
} from "lucide-react";

interface BusinessProfile {
  id: number;
  clientId: number;
  description: string | null;
  targetAudience: string | null;
  additionalInfo: string | null;
}

interface ProductItem {
  id: number;
  clientId: number;
  name: string;
  description: string | null;
  benefits: string | null;
  cost: string | null;
  price: string | null;
  category: string | null;
}

export default function BusinessProfilePage() {
  const [selectedClientId, setSelectedClientId] = useState<number | null>(null);
  const [description, setDescription] = useState("");
  const [targetAudience, setTargetAudience] = useState("");
  const [additionalInfo, setAdditionalInfo] = useState("");
  const [profileLoaded, setProfileLoaded] = useState(false);

  const [productDialogOpen, setProductDialogOpen] = useState(false);
  const [editingProduct, setEditingProduct] = useState<ProductItem | null>(null);
  const [productName, setProductName] = useState("");
  const [productDescription, setProductDescription] = useState("");
  const [productBenefits, setProductBenefits] = useState("");
  const [productCost, setProductCost] = useState("");
  const [productPrice, setProductPrice] = useState("");
  const [productCategory, setProductCategory] = useState("");

  const { toast } = useToast();

  const { data: clients } = useQuery<Client[]>({
    queryKey: ["/api/clients"],
  });

  if (!selectedClientId && clients && clients.length > 0) {
    setSelectedClientId(clients[0].id);
  }

  const { data: profile, isLoading: loadingProfile } = useQuery<BusinessProfile | null>({
    queryKey: ["/api/business-profile", selectedClientId],
    enabled: !!selectedClientId,
  });

  const { data: products = [], isLoading: loadingProducts } = useQuery<ProductItem[]>({
    queryKey: ["/api/product-catalog", selectedClientId],
    enabled: !!selectedClientId,
  });

  if (profile !== undefined && !profileLoaded && selectedClientId) {
    setDescription(profile?.description || "");
    setTargetAudience(profile?.targetAudience || "");
    setAdditionalInfo(profile?.additionalInfo || "");
    setProfileLoaded(true);
  }

  const saveProfileMutation = useMutation({
    mutationFn: async () => {
      return apiRequest("PUT", `/api/business-profile/${selectedClientId}`, {
        description: description || null,
        targetAudience: targetAudience || null,
        additionalInfo: additionalInfo || null,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/business-profile", selectedClientId] });
      toast({ title: "Perfil guardado", description: "La informacion del negocio se guardo correctamente." });
    },
    onError: () => {
      toast({ title: "Error", description: "No se pudo guardar el perfil.", variant: "destructive" });
    },
  });

  const createProductMutation = useMutation({
    mutationFn: async () => {
      return apiRequest("POST", `/api/product-catalog/${selectedClientId}`, {
        name: productName,
        description: productDescription || null,
        benefits: productBenefits || null,
        cost: productCost || null,
        price: productPrice || null,
        category: productCategory || null,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/product-catalog", selectedClientId] });
      resetProductForm();
      setProductDialogOpen(false);
      toast({ title: "Producto agregado", description: "El producto se agrego al catalogo." });
    },
    onError: () => {
      toast({ title: "Error", description: "No se pudo agregar el producto.", variant: "destructive" });
    },
  });

  const updateProductMutation = useMutation({
    mutationFn: async () => {
      if (!editingProduct) return;
      return apiRequest("PATCH", `/api/product-catalog/${selectedClientId}/${editingProduct.id}`, {
        name: productName,
        description: productDescription || null,
        benefits: productBenefits || null,
        cost: productCost || null,
        price: productPrice || null,
        category: productCategory || null,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/product-catalog", selectedClientId] });
      resetProductForm();
      setProductDialogOpen(false);
      setEditingProduct(null);
      toast({ title: "Producto actualizado" });
    },
    onError: () => {
      toast({ title: "Error", description: "No se pudo actualizar el producto.", variant: "destructive" });
    },
  });

  const deleteProductMutation = useMutation({
    mutationFn: async (productId: number) => {
      return apiRequest("DELETE", `/api/product-catalog/${selectedClientId}/${productId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/product-catalog", selectedClientId] });
      toast({ title: "Producto eliminado" });
    },
    onError: () => {
      toast({ title: "Error", description: "No se pudo eliminar el producto.", variant: "destructive" });
    },
  });

  const resetProductForm = () => {
    setProductName("");
    setProductDescription("");
    setProductBenefits("");
    setProductCost("");
    setProductPrice("");
    setProductCategory("");
  };

  const openEditProduct = (product: ProductItem) => {
    setEditingProduct(product);
    setProductName(product.name);
    setProductDescription(product.description || "");
    setProductBenefits(product.benefits || "");
    setProductCost(product.cost || "");
    setProductPrice(product.price || "");
    setProductCategory(product.category || "");
    setProductDialogOpen(true);
  };

  const handleClientChange = (clientId: number | null) => {
    setSelectedClientId(clientId);
    setProfileLoaded(false);
    setDescription("");
    setTargetAudience("");
    setAdditionalInfo("");
  };

  return (
    <div className="flex-1 p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold gradient-text" data-testid="text-page-title">Perfil de Negocio</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Configura la informacion de tu negocio para que la IA genere recomendaciones mas precisas
          </p>
        </div>
        <ClientSelector selectedClientId={selectedClientId} onClientChange={handleClientChange} data-testid="select-client" />
      </div>

      {!selectedClientId ? (
        <Card className="glass-effect">
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Building2 className="h-12 w-12 text-muted-foreground mb-4" />
            <p className="text-muted-foreground text-center">
              Selecciona un cliente para configurar su perfil de negocio
            </p>
          </CardContent>
        </Card>
      ) : (
        <Tabs defaultValue="profile" className="space-y-4">
          <TabsList data-testid="tabs-business">
            <TabsTrigger value="profile" data-testid="tab-profile">
              <Building2 className="h-4 w-4 mr-2" />
              Perfil del Negocio
            </TabsTrigger>
            <TabsTrigger value="catalog" data-testid="tab-catalog">
              <Package className="h-4 w-4 mr-2" />
              Catalogo de Productos
              {products.length > 0 && (
                <Badge variant="secondary" className="ml-2">{products.length}</Badge>
              )}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="profile" className="space-y-4">
            {loadingProfile ? (
              <Card className="glass-effect">
                <CardContent className="space-y-4 pt-6">
                  <Skeleton className="h-32 w-full" />
                  <Skeleton className="h-32 w-full" />
                  <Skeleton className="h-32 w-full" />
                </CardContent>
              </Card>
            ) : (
              <Card className="glass-effect">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Building2 className="h-5 w-5" />
                    Informacion del Negocio
                  </CardTitle>
                  <CardDescription>
                    Describe tu negocio para que la IA entienda tu contexto y genere mejores recomendaciones
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="space-y-2">
                    <Label htmlFor="description" className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-muted-foreground" />
                      Descripcion del Negocio
                    </Label>
                    <Textarea
                      id="description"
                      data-testid="input-description"
                      placeholder="Ej: Somos una tienda de ropa deportiva con 3 sucursales en Mexico. Vendemos ropa, calzado y accesorios deportivos para hombres, mujeres y ninos..."
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      rows={4}
                    />
                    <p className="text-xs text-muted-foreground">Incluye tipo de negocio, sector, modelo de negocio, numero de tiendas/sucursales, etc.</p>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="targetAudience" className="flex items-center gap-2">
                      <Target className="h-4 w-4 text-muted-foreground" />
                      Publico Objetivo
                    </Label>
                    <Textarea
                      id="targetAudience"
                      data-testid="input-target-audience"
                      placeholder="Ej: Personas de 18-45 anos, nivel socioeconomico medio-alto, interesadas en fitness y vida saludable. Principalmente en zonas urbanas..."
                      value={targetAudience}
                      onChange={(e) => setTargetAudience(e.target.value)}
                      rows={3}
                    />
                    <p className="text-xs text-muted-foreground">Demografia, comportamiento, intereses, ubicacion geografica de tus clientes</p>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="additionalInfo" className="flex items-center gap-2">
                      <Info className="h-4 w-4 text-muted-foreground" />
                      Informacion Adicional
                    </Label>
                    <Textarea
                      id="additionalInfo"
                      data-testid="input-additional-info"
                      placeholder="Ej: Temporada alta en enero (propositos de ano nuevo) y mayo-junio. Competimos con Nike Store y Adidas. Canal principal: tienda fisica (60%) y e-commerce (40%)..."
                      value={additionalInfo}
                      onChange={(e) => setAdditionalInfo(e.target.value)}
                      rows={4}
                    />
                    <p className="text-xs text-muted-foreground">Temporadas altas, competidores, canales de venta, objetivos de negocio, diferenciadores</p>
                  </div>

                  <div className="flex items-center gap-3 p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
                    <Sparkles className="h-5 w-5 text-blue-500 shrink-0" />
                    <p className="text-sm text-blue-400">
                      Esta informacion se usa automaticamente cuando pides recomendaciones en "Ask Your Data" para darte sugerencias personalizadas a tu negocio.
                    </p>
                  </div>

                  <Button
                    onClick={() => saveProfileMutation.mutate()}
                    disabled={saveProfileMutation.isPending}
                    className="w-full sm:w-auto"
                    data-testid="button-save-profile"
                  >
                    {saveProfileMutation.isPending ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4 mr-2" />
                    )}
                    Guardar Perfil
                  </Button>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          <TabsContent value="catalog" className="space-y-4">
            <Card className="glass-effect">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      <Package className="h-5 w-5" />
                      Catalogo de Productos
                    </CardTitle>
                    <CardDescription>
                      Agrega tus productos con costos, precios y beneficios para recomendaciones mas precisas
                    </CardDescription>
                  </div>
                  <Dialog open={productDialogOpen} onOpenChange={(open) => {
                    setProductDialogOpen(open);
                    if (!open) {
                      resetProductForm();
                      setEditingProduct(null);
                    }
                  }}>
                    <DialogTrigger asChild>
                      <Button data-testid="button-add-product">
                        <Plus className="h-4 w-4 mr-2" />
                        Agregar Producto
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="sm:max-w-lg">
                      <DialogHeader>
                        <DialogTitle>{editingProduct ? "Editar Producto" : "Agregar Producto"}</DialogTitle>
                        <DialogDescription>
                          {editingProduct ? "Actualiza la informacion del producto" : "Agrega un nuevo producto al catalogo"}
                        </DialogDescription>
                      </DialogHeader>
                      <div className="space-y-4">
                        <div className="space-y-2">
                          <Label htmlFor="productName">Nombre *</Label>
                          <Input
                            id="productName"
                            data-testid="input-product-name"
                            placeholder="Ej: Tenis Running Pro"
                            value={productName}
                            onChange={(e) => setProductName(e.target.value)}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="productCategory">Categoria</Label>
                          <Input
                            id="productCategory"
                            data-testid="input-product-category"
                            placeholder="Ej: Calzado Deportivo"
                            value={productCategory}
                            onChange={(e) => setProductCategory(e.target.value)}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="productDesc">Descripcion</Label>
                          <Textarea
                            id="productDesc"
                            data-testid="input-product-description"
                            placeholder="Ej: Tenis para correr con tecnologia de amortiguacion..."
                            value={productDescription}
                            onChange={(e) => setProductDescription(e.target.value)}
                            rows={2}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="productBenefits">Beneficios</Label>
                          <Textarea
                            id="productBenefits"
                            data-testid="input-product-benefits"
                            placeholder="Ej: Mayor comodidad, reduce lesiones, ideal para maratones..."
                            value={productBenefits}
                            onChange={(e) => setProductBenefits(e.target.value)}
                            rows={2}
                          />
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <Label htmlFor="productCost">Costo</Label>
                            <Input
                              id="productCost"
                              data-testid="input-product-cost"
                              placeholder="Ej: $850"
                              value={productCost}
                              onChange={(e) => setProductCost(e.target.value)}
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="productPrice">Precio de Venta</Label>
                            <Input
                              id="productPrice"
                              data-testid="input-product-price"
                              placeholder="Ej: $1,599"
                              value={productPrice}
                              onChange={(e) => setProductPrice(e.target.value)}
                            />
                          </div>
                        </div>
                      </div>
                      <DialogFooter>
                        <Button
                          variant="outline"
                          onClick={() => {
                            setProductDialogOpen(false);
                            resetProductForm();
                            setEditingProduct(null);
                          }}
                          data-testid="button-cancel-product"
                        >
                          Cancelar
                        </Button>
                        <Button
                          onClick={() => editingProduct ? updateProductMutation.mutate() : createProductMutation.mutate()}
                          disabled={!productName.trim() || createProductMutation.isPending || updateProductMutation.isPending}
                          data-testid="button-submit-product"
                        >
                          {(createProductMutation.isPending || updateProductMutation.isPending) ? (
                            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          ) : (
                            <Save className="h-4 w-4 mr-2" />
                          )}
                          {editingProduct ? "Actualizar" : "Agregar"}
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </Dialog>
                </div>
              </CardHeader>
              <CardContent>
                {loadingProducts ? (
                  <div className="space-y-3">
                    {[...Array(3)].map((_, i) => (
                      <Skeleton key={i} className="h-16 w-full" />
                    ))}
                  </div>
                ) : products.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-center">
                    <Package className="h-12 w-12 text-muted-foreground mb-4" />
                    <p className="text-muted-foreground mb-2">No hay productos en el catalogo</p>
                    <p className="text-xs text-muted-foreground">Agrega tus productos para que la IA los considere en sus recomendaciones</p>
                  </div>
                ) : (
                  <div className="rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Producto</TableHead>
                          <TableHead className="hidden md:table-cell">Categoria</TableHead>
                          <TableHead className="hidden lg:table-cell">Costo</TableHead>
                          <TableHead className="hidden lg:table-cell">Precio</TableHead>
                          <TableHead className="w-[100px]">Acciones</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {products.map((product) => (
                          <TableRow key={product.id} data-testid={`row-product-${product.id}`}>
                            <TableCell>
                              <div>
                                <p className="font-medium">{product.name}</p>
                                {product.description && (
                                  <p className="text-xs text-muted-foreground line-clamp-1">{product.description}</p>
                                )}
                              </div>
                            </TableCell>
                            <TableCell className="hidden md:table-cell">
                              {product.category ? (
                                <Badge variant="secondary">{product.category}</Badge>
                              ) : (
                                <span className="text-muted-foreground text-sm">-</span>
                              )}
                            </TableCell>
                            <TableCell className="hidden lg:table-cell">
                              {product.cost || <span className="text-muted-foreground">-</span>}
                            </TableCell>
                            <TableCell className="hidden lg:table-cell">
                              {product.price || <span className="text-muted-foreground">-</span>}
                            </TableCell>
                            <TableCell>
                              <div className="flex items-center gap-1">
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8"
                                  onClick={() => openEditProduct(product)}
                                  data-testid={`button-edit-product-${product.id}`}
                                >
                                  <Pencil className="h-4 w-4" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8 text-destructive hover:text-destructive"
                                  onClick={() => deleteProductMutation.mutate(product.id)}
                                  data-testid={`button-delete-product-${product.id}`}
                                >
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
