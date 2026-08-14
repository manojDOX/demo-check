import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Mail, Phone, MapPin } from "lucide-react";

interface ContactSectionProps {
  content: {
    title?: string;
    subtitle?: string;
    fields?: string[];
    submitText?: string;
    successMessage?: string;
  };
  styles: {
    backgroundColor?: string;
    textColor?: string;
    padding?: string;
  };
}

export function ContactSection({ content, styles }: ContactSectionProps) {
  return (
    <section
      style={{
        backgroundColor: styles.backgroundColor || "#1a1a2e",
        color: styles.textColor || "#ffffff",
        padding: styles.padding || "60px 20px",
      }}
    >
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-12">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">
            {content.title || "Contactanos"}
          </h2>
          <p className="text-lg opacity-70">
            {content.subtitle || "Estamos aqui para ayudarte"}
          </p>
        </div>
        <div className="grid md:grid-cols-2 gap-12">
          <div className="space-y-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center flex-shrink-0">
                <Mail className="h-5 w-5 text-primary" />
              </div>
              <div>
                <h4 className="font-medium">Email</h4>
                <p className="opacity-70">contacto@ejemplo.com</p>
              </div>
            </div>
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center flex-shrink-0">
                <Phone className="h-5 w-5 text-primary" />
              </div>
              <div>
                <h4 className="font-medium">Telefono</h4>
                <p className="opacity-70">+1 (555) 123-4567</p>
              </div>
            </div>
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center flex-shrink-0">
                <MapPin className="h-5 w-5 text-primary" />
              </div>
              <div>
                <h4 className="font-medium">Direccion</h4>
                <p className="opacity-70">123 Calle Principal, Ciudad</p>
              </div>
            </div>
          </div>
          <form className="space-y-4" onSubmit={(e) => e.preventDefault()}>
            <div>
              <Label htmlFor="name" className="text-inherit">Nombre</Label>
              <Input id="name" placeholder="Tu nombre" className="mt-1 bg-white/10 border-white/20" />
            </div>
            <div>
              <Label htmlFor="email" className="text-inherit">Email</Label>
              <Input id="email" type="email" placeholder="tu@email.com" className="mt-1 bg-white/10 border-white/20" />
            </div>
            <div>
              <Label htmlFor="message" className="text-inherit">Mensaje</Label>
              <Textarea id="message" placeholder="Tu mensaje..." className="mt-1 bg-white/10 border-white/20" rows={4} />
            </div>
            <Button type="submit" className="w-full">
              {content.submitText || "Enviar Mensaje"}
            </Button>
          </form>
        </div>
      </div>
    </section>
  );
}
