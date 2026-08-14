import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Sparkles, Layers, ArrowLeft, Bell } from "lucide-react";
import { Link } from "wouter";

interface ComingSoonProps {
  title?: string;
  description?: string;
  feature?: "builder" | "personalization";
}

export default function ComingSoon({
  title = "Dynamic Persona",
  description = "AI-powered personalized website experiences are coming soon.",
  feature = "builder",
}: ComingSoonProps) {
  const featureDetails = {
    builder: {
      title: "Page Builder",
      description: "Create beautiful, personalized landing pages with our drag-and-drop builder. Design pages that automatically adapt to each visitor's preferences and behavior.",
      features: [
        "Drag-and-drop page builder",
        "Pre-built template library",
        "Mobile-responsive designs",
        "A/B testing built-in",
      ],
    },
    personalization: {
      title: "Smart Personalization",
      description: "Deliver unique experiences to every visitor based on their behavior, preferences, and segment membership.",
      features: [
        "Real-time visitor tracking",
        "Behavioral segmentation",
        "Dynamic content zones",
        "Conversion optimization",
      ],
    },
  };

  const details = featureDetails[feature];

  return (
    <div className="flex-1 flex items-center justify-center p-6">
      <Card className="max-w-2xl w-full">
        <CardContent className="p-8 text-center space-y-6">
          <div className="flex justify-center">
            <div className="h-20 w-20 rounded-full bg-gradient-to-br from-primary to-accent flex items-center justify-center">
              {feature === "builder" ? (
                <Layers className="h-10 w-10 text-white" />
              ) : (
                <Sparkles className="h-10 w-10 text-white" />
              )}
            </div>
          </div>

          <div className="space-y-2">
            <h1 className="text-3xl font-bold gradient-text">{details.title}</h1>
            <p className="text-lg text-muted-foreground max-w-md mx-auto">
              {details.description}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4 max-w-md mx-auto text-left">
            {details.features.map((f, i) => (
              <div key={i} className="flex items-center gap-2 p-3 rounded-lg bg-muted/50">
                <Sparkles className="h-4 w-4 text-primary shrink-0" />
                <span className="text-sm">{f}</span>
              </div>
            ))}
          </div>

          <div className="flex items-center justify-center gap-4 pt-4">
            <Link href="/">
              <Button variant="outline" className="gap-2" data-testid="button-back-dashboard">
                <ArrowLeft className="h-4 w-4" />
                Back to Dashboard
              </Button>
            </Link>
            <Button className="gap-2" data-testid="button-notify-me">
              <Bell className="h-4 w-4" />
              Notify Me
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
