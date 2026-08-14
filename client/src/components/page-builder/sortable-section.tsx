import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button } from "@/components/ui/button";
import { SectionRenderer } from "./section-renderer";
import type { PageSection } from "@shared/schema";
import { GripVertical, Trash2, Edit } from "lucide-react";
import { useState } from "react";

interface SortableSectionProps {
  section: PageSection;
  onUpdate: (id: number, content: object, styles: object) => void;
  onDelete: (id: number) => void;
}

export function SortableSection({ section, onUpdate, onDelete }: SortableSectionProps) {
  const [isHovered, setIsHovered] = useState(false);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: section.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="relative group"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      data-testid={`sortable-section-${section.id}`}
    >
      <div
        className={`absolute left-0 top-0 bottom-0 w-8 flex items-center justify-center bg-primary/10 opacity-0 group-hover:opacity-100 transition-opacity cursor-grab z-10 ${
          isDragging ? "cursor-grabbing" : ""
        }`}
        {...attributes}
        {...listeners}
      >
        <GripVertical className="h-5 w-5 text-primary" />
      </div>

      <div
        className={`absolute right-2 top-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity z-10`}
      >
        <Button
          variant="secondary"
          size="icon"
          className="h-8 w-8"
          onClick={() => onDelete(section.id)}
          data-testid={`button-delete-section-${section.id}`}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      <div className={`${isHovered ? "ring-2 ring-primary ring-inset" : ""}`}>
        <SectionRenderer section={section} />
      </div>
    </div>
  );
}
