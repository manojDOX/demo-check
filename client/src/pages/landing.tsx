import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { 
  Database, 
  BarChart3, 
  Users, 
  Sparkles, 
  MessageSquare,
  ArrowRight,
  Shield,
  Zap
} from "lucide-react";
import xiomaraLogo from "@assets/logo_xiomara_2_1769277766982.png";

export default function Landing() {
  return (
    <div className="min-h-screen bg-background">
      <header className="fixed top-0 left-0 right-0 z-50 border-b border-border/50 backdrop-blur-md bg-background/80">
        <div className="container mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src={xiomaraLogo} alt="Xiomara" className="h-8" />
          </div>
          <Button asChild data-testid="button-login-header">
            <a href="/api/login">Iniciar Sesion</a>
          </Button>
        </div>
      </header>

      <main className="pt-16">
        <section className="relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-br from-primary/5 via-transparent to-accent/5" />
          <div className="container mx-auto px-6 py-24 lg:py-32">
            <div className="max-w-3xl mx-auto text-center">
              <h1 className="text-4xl lg:text-6xl font-bold tracking-tight mb-6">
                Transforma Tus Datos de Retail en{" "}
                <span className="gradient-text">Insights Accionables</span>
              </h1>
              <p className="text-xl text-muted-foreground mb-8 max-w-2xl mx-auto">
                Plataforma de inteligencia de marketing impulsada por IA. Haz preguntas en lenguaje natural, 
                obtiene analisis instantaneo y exporta segmentos a tu CRM.
              </p>
              <div className="flex flex-col sm:flex-row gap-4 justify-center">
                <Button size="lg" asChild data-testid="button-get-started">
                  <a href="/api/login" className="gap-2">
                    Comenzar <ArrowRight className="h-4 w-4" />
                  </a>
                </Button>
              </div>
              <p className="mt-4 text-sm text-muted-foreground">
                Gratis para empezar. No se requiere tarjeta de credito.
              </p>
            </div>
          </div>
        </section>

        <section className="py-20 bg-muted/30">
          <div className="container mx-auto px-6">
            <h2 className="text-3xl font-bold text-center mb-12">
              Todo lo que Necesitas para Marketing Basado en Datos
            </h2>
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
              <Card className="hover-elevate">
                <CardContent className="pt-6">
                  <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                    <MessageSquare className="h-6 w-6 text-primary" />
                  </div>
                  <h3 className="text-xl font-semibold mb-2">Consultas en Lenguaje Natural</h3>
                  <p className="text-muted-foreground">
                    Haz preguntas en espanol. Nuestra IA las traduce a SQL y devuelve 
                    resultados visualizados al instante.
                  </p>
                </CardContent>
              </Card>

              <Card className="hover-elevate">
                <CardContent className="pt-6">
                  <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                    <BarChart3 className="h-6 w-6 text-primary" />
                  </div>
                  <h3 className="text-xl font-semibold mb-2">9 KPIs de Retail</h3>
                  <p className="text-muted-foreground">
                    Monitorea Ventas Totales, AOV, LTV del Cliente, Tasa de Recurrencia, 
                    Abandono de Carrito y mas en un panel visual.
                  </p>
                </CardContent>
              </Card>

              <Card className="hover-elevate">
                <CardContent className="pt-6">
                  <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                    <Users className="h-6 w-6 text-primary" />
                  </div>
                  <h3 className="text-xl font-semibold mb-2">Segmentacion Inteligente</h3>
                  <p className="text-muted-foreground">
                    Segmentos de clientes generados por IA o crea los tuyos. Exporta directamente a 
                    GoHighLevel CRM con etiquetas personalizadas.
                  </p>
                </CardContent>
              </Card>

              <Card className="hover-elevate">
                <CardContent className="pt-6">
                  <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                    <Database className="h-6 w-6 text-primary" />
                  </div>
                  <h3 className="text-xl font-semibold mb-2">Integracion con BigQuery</h3>
                  <p className="text-muted-foreground">
                    Conecta multiples cuentas de BigQuery. Gestiona diferentes clientes desde una 
                    plataforma unificada.
                  </p>
                </CardContent>
              </Card>

              <Card className="hover-elevate">
                <CardContent className="pt-6">
                  <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                    <Zap className="h-6 w-6 text-primary" />
                  </div>
                  <h3 className="text-xl font-semibold mb-2">Analisis en Tiempo Real</h3>
                  <p className="text-muted-foreground">
                    Metricas pre-calculadas diarias mas consultas bajo demanda. Obtiene respuestas en segundos, 
                    no en horas.
                  </p>
                </CardContent>
              </Card>

              <Card className="hover-elevate">
                <CardContent className="pt-6">
                  <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                    <Shield className="h-6 w-6 text-primary" />
                  </div>
                  <h3 className="text-xl font-semibold mb-2">Seguridad Empresarial</h3>
                  <p className="text-muted-foreground">
                    Tus datos permanecen en tu BigQuery. Nunca almacenamos datos crudos de clientes. 
                    Infraestructura compatible con SOC 2.
                  </p>
                </CardContent>
              </Card>
            </div>
          </div>
        </section>

        <section className="py-20">
          <div className="container mx-auto px-6 text-center">
            <h2 className="text-3xl font-bold mb-4">
              Listo para desbloquear tus datos?
            </h2>
            <p className="text-lg text-muted-foreground mb-8 max-w-xl mx-auto">
              Unete a los equipos de marketing que confian en Marketing Intel para tomar decisiones basadas en datos.
            </p>
            <Button size="lg" asChild data-testid="button-start-free">
              <a href="/api/login" className="gap-2">
                Comenzar Gratis <ArrowRight className="h-4 w-4" />
              </a>
            </Button>
          </div>
        </section>
      </main>

      <footer className="border-t border-border py-8">
        <div className="container mx-auto px-6 text-center text-sm text-muted-foreground">
          <p>2026 Marketing Intelligence Platform. Todos los derechos reservados.</p>
        </div>
      </footer>
    </div>
  );
}
