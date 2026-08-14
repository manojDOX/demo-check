import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Users, ArrowRight, Building2, Mail } from "lucide-react";
import xiomaraLogo from "@assets/logo_xiomara_2_1769277766982.png";

export default function Invite() {
  const params = new URLSearchParams(window.location.search);
  const inviterName = params.get("inviter") || "Tu administrador";
  const email = params.get("email") || "";
  const clientNames = params.get("clients")?.split(",").filter(Boolean) || [];

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b border-border/50 backdrop-blur-md bg-background/80">
        <div className="container mx-auto px-6 h-16 flex items-center justify-center">
          <img src={xiomaraLogo} alt="Xiomara" className="h-8" />
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          <Card className="border-border/50 bg-card/50 backdrop-blur-sm">
            <CardContent className="pt-8 pb-8 px-8">
              <div className="text-center mb-8">
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-primary/10 mb-4">
                  <Users className="h-8 w-8 text-primary" />
                </div>
                <h1 className="text-2xl font-bold mb-2">Has sido invitado/a</h1>
                <p className="text-muted-foreground">
                  <span className="text-primary font-semibold">{inviterName}</span>{" "}
                  te ha invitado a colaborar en la plataforma Xiomara.
                </p>
              </div>

              {clientNames.length > 0 && (
                <div className="mb-6">
                  <p className="text-sm text-muted-foreground mb-3 flex items-center gap-2">
                    <Building2 className="h-4 w-4" />
                    Clientes asignados:
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {clientNames.map((name, i) => (
                      <span
                        key={i}
                        className="inline-flex items-center px-3 py-1.5 rounded-full text-sm font-medium bg-primary/10 text-primary border border-primary/20"
                      >
                        {name.trim()}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {email && (
                <div className="mb-6 p-3 rounded-lg bg-muted/50 border border-border/50">
                  <p className="text-sm text-muted-foreground flex items-center gap-2">
                    <Mail className="h-4 w-4" />
                    Inicia sesion con:
                  </p>
                  <p className="text-sm font-medium mt-1">{email}</p>
                </div>
              )}

              <Button size="lg" className="w-full gap-2" asChild data-testid="button-invite-login">
                <a href="/api/login">
                  Crear cuenta y acceder <ArrowRight className="h-4 w-4" />
                </a>
              </Button>

              <p className="text-xs text-muted-foreground text-center mt-4">
                Al iniciar sesion, tendras acceso a los datos de los clientes que te fueron asignados.
              </p>
            </CardContent>
          </Card>
        </div>
      </main>

      <footer className="border-t border-border/50 py-4">
        <p className="text-center text-xs text-muted-foreground">
          &copy; 2026 Xiomara. Todos los derechos reservados.
        </p>
      </footer>
    </div>
  );
}
