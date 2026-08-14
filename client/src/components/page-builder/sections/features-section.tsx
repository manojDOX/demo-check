import { Star, Zap, Shield, Heart, Target, Rocket } from "lucide-react";

interface Feature {
  title: string;
  description: string;
  icon: string;
}

interface FeaturesSectionProps {
  content: {
    title?: string;
    subtitle?: string;
    features?: Feature[];
  };
  styles: {
    backgroundColor?: string;
    textColor?: string;
    padding?: string;
  };
}

const iconMap: Record<string, any> = {
  star: Star,
  zap: Zap,
  shield: Shield,
  heart: Heart,
  target: Target,
  rocket: Rocket,
};

export function FeaturesSection({ content, styles }: FeaturesSectionProps) {
  const features = content.features || [
    { title: "Caracteristica 1", description: "Descripcion de la caracteristica", icon: "star" },
    { title: "Caracteristica 2", description: "Descripcion de la caracteristica", icon: "zap" },
    { title: "Caracteristica 3", description: "Descripcion de la caracteristica", icon: "shield" },
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
            {content.title || "Nuestras Caracteristicas"}
          </h2>
          <p className="text-lg opacity-70 max-w-2xl mx-auto">
            {content.subtitle || "Lo que nos hace diferentes"}
          </p>
        </div>
        <div className="grid md:grid-cols-3 gap-8">
          {features.map((feature, index) => {
            const IconComponent = iconMap[feature.icon] || Star;
            return (
              <div key={index} className="text-center p-6">
                <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-primary/10 flex items-center justify-center">
                  <IconComponent className="h-8 w-8 text-primary" />
                </div>
                <h3 className="text-xl font-semibold mb-2">{feature.title}</h3>
                <p className="opacity-70">{feature.description}</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
