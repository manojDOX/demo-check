import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent } from "@/components/ui/card";

interface TeamMember {
  name: string;
  role: string;
  bio: string;
  photo?: string;
}

interface TeamSectionProps {
  content: {
    title?: string;
    subtitle?: string;
    members?: TeamMember[];
  };
  styles: {
    backgroundColor?: string;
    textColor?: string;
    padding?: string;
  };
}

export function TeamSection({ content, styles }: TeamSectionProps) {
  const members = content.members || [
    { name: "Ana Martinez", role: "CEO", bio: "Liderando la vision de la empresa", photo: "" },
    { name: "Carlos Lopez", role: "CTO", bio: "Arquitectura y tecnologia", photo: "" },
    { name: "Laura Sanchez", role: "CMO", bio: "Estrategia de marketing", photo: "" },
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
        <div className="text-center mb-12">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">
            {content.title || "Nuestro Equipo"}
          </h2>
          <p className="text-lg opacity-70 max-w-2xl mx-auto">
            {content.subtitle || "Conoce a las personas detras del proyecto"}
          </p>
        </div>
        <div className="grid md:grid-cols-3 gap-8">
          {members.map((member, index) => (
            <Card key={index} className="text-center bg-white dark:bg-card">
              <CardContent className="pt-8 pb-6">
                <Avatar className="w-24 h-24 mx-auto mb-4">
                  <AvatarImage src={member.photo} />
                  <AvatarFallback className="text-2xl">
                    {member.name.split(" ").map((n) => n[0]).join("")}
                  </AvatarFallback>
                </Avatar>
                <h3 className="text-xl font-semibold mb-1">{member.name}</h3>
                <p className="text-primary font-medium mb-2">{member.role}</p>
                <p className="text-sm opacity-70">{member.bio}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
