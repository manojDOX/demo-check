import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Check } from "lucide-react";

interface Plan {
  name: string;
  price: string;
  period: string;
  features: string[];
  ctaText: string;
  featured: boolean;
}

interface PricingSectionProps {
  content: {
    title?: string;
    subtitle?: string;
    plans?: Plan[];
  };
  styles: {
    backgroundColor?: string;
    textColor?: string;
    padding?: string;
  };
}

export function PricingSection({ content, styles }: PricingSectionProps) {
  const plans = content.plans || [
    { name: "Basico", price: "$29", period: "/mes", features: ["5 usuarios", "10GB almacenamiento"], ctaText: "Elegir Plan", featured: false },
    { name: "Pro", price: "$79", period: "/mes", features: ["20 usuarios", "100GB almacenamiento"], ctaText: "Elegir Plan", featured: true },
    { name: "Enterprise", price: "$199", period: "/mes", features: ["Usuarios ilimitados", "1TB almacenamiento"], ctaText: "Contactar", featured: false },
  ];

  return (
    <section
      style={{
        backgroundColor: styles.backgroundColor || "#ffffff",
        color: styles.textColor || "#1a1a2e",
        padding: styles.padding || "60px 20px",
      }}
    >
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-12">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">
            {content.title || "Planes y Precios"}
          </h2>
          <p className="text-lg opacity-70 max-w-2xl mx-auto">
            {content.subtitle || "Elige el plan que mejor se adapte a ti"}
          </p>
        </div>
        <div className="grid md:grid-cols-3 gap-8">
          {plans.map((plan, index) => (
            <Card
              key={index}
              className={`relative ${plan.featured ? "border-primary shadow-lg scale-105" : ""}`}
            >
              {plan.featured && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-primary text-primary-foreground px-4 py-1 rounded-full text-sm font-medium">
                  Popular
                </div>
              )}
              <CardHeader className="text-center pb-0">
                <h3 className="text-xl font-semibold">{plan.name}</h3>
                <div className="mt-4">
                  <span className="text-4xl font-bold">{plan.price}</span>
                  <span className="text-muted-foreground">{plan.period}</span>
                </div>
              </CardHeader>
              <CardContent className="pt-6">
                <ul className="space-y-3">
                  {plan.features.map((feature, i) => (
                    <li key={i} className="flex items-center gap-2">
                      <Check className="h-5 w-5 text-primary" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
              <CardFooter>
                <Button
                  className="w-full"
                  variant={plan.featured ? "default" : "outline"}
                >
                  {plan.ctaText}
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
