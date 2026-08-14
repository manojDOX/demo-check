import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent } from "@/components/ui/card";
import { Quote } from "lucide-react";

interface Testimonial {
  name: string;
  role: string;
  quote: string;
  avatar?: string;
}

interface TestimonialsSectionProps {
  content: {
    title?: string;
    testimonials?: Testimonial[];
  };
  styles: {
    backgroundColor?: string;
    textColor?: string;
    padding?: string;
  };
}

export function TestimonialsSection({ content, styles }: TestimonialsSectionProps) {
  const testimonials = content.testimonials || [
    { name: "Maria Garcia", role: "CEO, Empresa", quote: "Excelente servicio, muy recomendado.", avatar: "" },
    { name: "Juan Perez", role: "Director, Compania", quote: "Superaron nuestras expectativas.", avatar: "" },
  ];

  return (
    <section
      style={{
        backgroundColor: styles.backgroundColor || "#f8f9fa",
        color: styles.textColor || "#1a1a2e",
        padding: styles.padding || "60px 20px",
      }}
    >
      <div className="max-w-6xl mx-auto">
        <h2 className="text-3xl md:text-4xl font-bold text-center mb-12">
          {content.title || "Lo que dicen nuestros clientes"}
        </h2>
        <div className="grid md:grid-cols-2 gap-8">
          {testimonials.map((testimonial, index) => (
            <Card key={index} className="bg-white dark:bg-card">
              <CardContent className="p-6">
                <Quote className="h-8 w-8 text-primary/30 mb-4" />
                <p className="text-lg mb-6 italic">"{testimonial.quote}"</p>
                <div className="flex items-center gap-4">
                  <Avatar>
                    <AvatarImage src={testimonial.avatar} />
                    <AvatarFallback>
                      {testimonial.name.split(" ").map((n) => n[0]).join("")}
                    </AvatarFallback>
                  </Avatar>
                  <div>
                    <p className="font-semibold">{testimonial.name}</p>
                    <p className="text-sm opacity-70">{testimonial.role}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
