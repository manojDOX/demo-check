import type { PageSection } from "@shared/schema";
import { HeroSection } from "./sections/hero-section";
import { FeaturesSection } from "./sections/features-section";
import { TestimonialsSection } from "./sections/testimonials-section";
import { PricingSection } from "./sections/pricing-section";
import { TeamSection } from "./sections/team-section";
import { ContactSection } from "./sections/contact-section";

interface SectionRendererProps {
  section: PageSection;
}

export function SectionRenderer({ section }: SectionRendererProps) {
  const content = section.content as Record<string, any>;
  const styles = section.styles as Record<string, any>;

  switch (section.sectionType) {
    case "hero":
      return <HeroSection content={content} styles={styles} />;
    case "features":
      return <FeaturesSection content={content} styles={styles} />;
    case "testimonials":
      return <TestimonialsSection content={content} styles={styles} />;
    case "pricing":
      return <PricingSection content={content} styles={styles} />;
    case "team":
      return <TeamSection content={content} styles={styles} />;
    case "contact":
      return <ContactSection content={content} styles={styles} />;
    default:
      return (
        <div className="p-8 bg-muted text-center">
          <p className="text-muted-foreground">
            Seccion desconocida: {section.sectionType}
          </p>
        </div>
      );
  }
}
