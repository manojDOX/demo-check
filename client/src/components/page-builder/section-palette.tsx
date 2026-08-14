import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Card, CardContent } from "@/components/ui/card";
import {
  Layout,
  Grid3X3,
  MessageSquareQuote,
  CreditCard,
  Users,
  Mail,
} from "lucide-react";

interface SectionPaletteProps {
  open: boolean;
  onClose: () => void;
  onSelect: (sectionType: string, content: object, styles: object) => void;
}

const sectionTypes = [
  {
    type: "hero",
    name: "Hero",
    description: "Seccion principal con titulo, subtitulo y CTA",
    icon: Layout,
    defaultContent: {
      title: "Bienvenido a tu sitio",
      subtitle: "Una descripcion breve de lo que ofreces",
      ctaText: "Comenzar",
      ctaLink: "#",
      backgroundImage: "",
    },
    defaultStyles: {
      backgroundColor: "#1a1a2e",
      textColor: "#ffffff",
      padding: "80px",
    },
  },
  {
    type: "features",
    name: "Caracteristicas",
    description: "Muestra las caracteristicas de tu producto o servicio",
    icon: Grid3X3,
    defaultContent: {
      title: "Nuestras Caracteristicas",
      subtitle: "Lo que nos hace diferentes",
      features: [
        {
          title: "Caracteristica 1",
          description: "Descripcion de la caracteristica",
          icon: "star",
        },
        {
          title: "Caracteristica 2",
          description: "Descripcion de la caracteristica",
          icon: "zap",
        },
        {
          title: "Caracteristica 3",
          description: "Descripcion de la caracteristica",
          icon: "shield",
        },
      ],
    },
    defaultStyles: {
      backgroundColor: "#ffffff",
      textColor: "#1a1a2e",
      padding: "60px",
    },
  },
  {
    type: "testimonials",
    name: "Testimonios",
    description: "Opiniones de clientes satisfechos",
    icon: MessageSquareQuote,
    defaultContent: {
      title: "Lo que dicen nuestros clientes",
      testimonials: [
        {
          name: "Maria Garcia",
          role: "CEO, Empresa",
          quote: "Excelente servicio, muy recomendado.",
          avatar: "",
        },
        {
          name: "Juan Perez",
          role: "Director, Compania",
          quote: "Superaron nuestras expectativas.",
          avatar: "",
        },
      ],
    },
    defaultStyles: {
      backgroundColor: "#f8f9fa",
      textColor: "#1a1a2e",
      padding: "60px",
    },
  },
  {
    type: "pricing",
    name: "Precios",
    description: "Tabla de precios y planes",
    icon: CreditCard,
    defaultContent: {
      title: "Planes y Precios",
      subtitle: "Elige el plan que mejor se adapte a ti",
      plans: [
        {
          name: "Basico",
          price: "$29",
          period: "/mes",
          features: ["5 usuarios", "10GB almacenamiento", "Soporte email"],
          ctaText: "Elegir Plan",
          featured: false,
        },
        {
          name: "Pro",
          price: "$79",
          period: "/mes",
          features: ["20 usuarios", "100GB almacenamiento", "Soporte prioritario"],
          ctaText: "Elegir Plan",
          featured: true,
        },
        {
          name: "Enterprise",
          price: "$199",
          period: "/mes",
          features: ["Usuarios ilimitados", "1TB almacenamiento", "Soporte 24/7"],
          ctaText: "Contactar",
          featured: false,
        },
      ],
    },
    defaultStyles: {
      backgroundColor: "#ffffff",
      textColor: "#1a1a2e",
      padding: "60px",
    },
  },
  {
    type: "team",
    name: "Equipo",
    description: "Presenta a los miembros de tu equipo",
    icon: Users,
    defaultContent: {
      title: "Nuestro Equipo",
      subtitle: "Conoce a las personas detras del proyecto",
      members: [
        {
          name: "Ana Martinez",
          role: "CEO",
          bio: "Liderando la vision de la empresa",
          photo: "",
        },
        {
          name: "Carlos Lopez",
          role: "CTO",
          bio: "Arquitectura y tecnologia",
          photo: "",
        },
        {
          name: "Laura Sanchez",
          role: "CMO",
          bio: "Estrategia de marketing",
          photo: "",
        },
      ],
    },
    defaultStyles: {
      backgroundColor: "#f8f9fa",
      textColor: "#1a1a2e",
      padding: "60px",
    },
  },
  {
    type: "contact",
    name: "Contacto",
    description: "Formulario de contacto para tus visitantes",
    icon: Mail,
    defaultContent: {
      title: "Contactanos",
      subtitle: "Estamos aqui para ayudarte",
      fields: ["nombre", "email", "mensaje"],
      submitText: "Enviar Mensaje",
      successMessage: "Gracias por contactarnos!",
    },
    defaultStyles: {
      backgroundColor: "#1a1a2e",
      textColor: "#ffffff",
      padding: "60px",
    },
  },
];

export function SectionPalette({ open, onClose, onSelect }: SectionPaletteProps) {
  const handleSelect = (section: typeof sectionTypes[0]) => {
    onSelect(section.type, section.defaultContent, section.defaultStyles);
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Agregar Seccion</DialogTitle>
        </DialogHeader>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mt-4">
          {sectionTypes.map((section) => (
            <Card
              key={section.type}
              className="cursor-pointer hover-elevate transition-all"
              onClick={() => handleSelect(section)}
              data-testid={`palette-section-${section.type}`}
            >
              <CardContent className="p-4 text-center">
                <div className="w-12 h-12 mx-auto mb-3 rounded-lg bg-primary/10 flex items-center justify-center">
                  <section.icon className="h-6 w-6 text-primary" />
                </div>
                <h3 className="font-medium mb-1">{section.name}</h3>
                <p className="text-xs text-muted-foreground">{section.description}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
