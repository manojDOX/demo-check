import { Button } from "@/components/ui/button";

interface HeroSectionProps {
  content: {
    title?: string;
    subtitle?: string;
    ctaText?: string;
    ctaLink?: string;
    backgroundImage?: string;
  };
  styles: {
    backgroundColor?: string;
    textColor?: string;
    padding?: string;
  };
}

export function HeroSection({ content, styles }: HeroSectionProps) {
  return (
    <section
      className="relative flex flex-col items-center justify-center text-center"
      style={{
        backgroundColor: styles.backgroundColor || "#1a1a2e",
        color: styles.textColor || "#ffffff",
        padding: styles.padding || "80px 20px",
        backgroundImage: content.backgroundImage ? `url(${content.backgroundImage})` : undefined,
        backgroundSize: "cover",
        backgroundPosition: "center",
        minHeight: "400px",
      }}
    >
      {content.backgroundImage && (
        <div className="absolute inset-0 bg-black/50" />
      )}
      <div className="relative z-10 max-w-4xl mx-auto">
        <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold mb-6">
          {content.title || "Bienvenido a tu sitio"}
        </h1>
        <p className="text-lg md:text-xl opacity-90 mb-8 max-w-2xl mx-auto">
          {content.subtitle || "Una descripcion breve de lo que ofreces"}
        </p>
        <Button
          size="lg"
          className="bg-primary hover:bg-primary/90"
        >
          {content.ctaText || "Comenzar"}
        </Button>
      </div>
    </section>
  );
}
