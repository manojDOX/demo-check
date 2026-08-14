import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CalendarIcon } from "lucide-react";
import { format, subDays, startOfMonth, endOfMonth, startOfQuarter, endOfQuarter, startOfYear, subMonths, subQuarters } from "date-fns";
import { es } from "date-fns/locale";
import { cn } from "@/lib/utils";
import { DateRange } from "react-day-picker";

export type DatePreset = "7d" | "30d" | "3m" | "this_month" | "last_month" | "this_quarter" | "last_quarter" | "this_year" | "custom";

export interface DateRangeValue {
  from: Date;
  to: Date;
  preset: DatePreset;
}

interface DateRangeFilterProps {
  value: DateRangeValue;
  onChange: (value: DateRangeValue) => void;
  className?: string;
}

const presetOptions: { value: DatePreset; label: string }[] = [
  { value: "7d", label: "Últimos 7 días" },
  { value: "30d", label: "Últimos 30 días" },
  { value: "3m", label: "Últimos 3 meses" },
  { value: "this_month", label: "Este mes" },
  { value: "last_month", label: "Mes anterior" },
  { value: "this_quarter", label: "Este trimestre" },
  { value: "last_quarter", label: "Trimestre anterior" },
  { value: "this_year", label: "Este año" },
  { value: "custom", label: "Personalizado" },
];

export function getDateRangeFromPreset(preset: DatePreset): { from: Date; to: Date } {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
  
  switch (preset) {
    case "7d":
      return { from: subDays(today, 6), to: today };
    case "30d":
      return { from: subDays(today, 29), to: today };
    case "3m":
      return { from: subMonths(today, 3), to: today };
    case "this_month":
      return { from: startOfMonth(today), to: today };
    case "last_month": {
      const lastMonth = subMonths(today, 1);
      return { from: startOfMonth(lastMonth), to: endOfMonth(lastMonth) };
    }
    case "this_quarter":
      return { from: startOfQuarter(today), to: today };
    case "last_quarter": {
      const lastQuarter = subQuarters(today, 1);
      return { from: startOfQuarter(lastQuarter), to: endOfQuarter(lastQuarter) };
    }
    case "this_year":
      return { from: startOfYear(today), to: today };
    case "custom":
    default:
      return { from: subDays(today, 29), to: today };
  }
}

export function getDefaultDateRange(): DateRangeValue {
  const range = getDateRangeFromPreset("3m");
  return { ...range, preset: "3m" };
}

export function DateRangeFilter({ value, onChange, className }: DateRangeFilterProps) {
  const [isCalendarOpen, setIsCalendarOpen] = useState(false);

  const handlePresetChange = (preset: DatePreset) => {
    if (preset === "custom") {
      setIsCalendarOpen(true);
      onChange({ ...value, preset: "custom" });
    } else {
      const range = getDateRangeFromPreset(preset);
      onChange({ ...range, preset });
    }
  };

  const handleDateRangeChange = (range: DateRange | undefined) => {
    if (range?.from && range?.to) {
      onChange({
        from: range.from,
        to: range.to,
        preset: "custom",
      });
    }
  };

  const formatDateRange = () => {
    if (value.preset !== "custom") {
      return presetOptions.find(p => p.value === value.preset)?.label || "";
    }
    return `${format(value.from, "dd MMM", { locale: es })} - ${format(value.to, "dd MMM yyyy", { locale: es })}`;
  };

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <Select value={value.preset} onValueChange={(v) => handlePresetChange(v as DatePreset)}>
        <SelectTrigger className="w-[180px]" data-testid="select-date-preset">
          <SelectValue placeholder="Selecciona período" />
        </SelectTrigger>
        <SelectContent>
          {presetOptions.map((option) => (
            <SelectItem key={option.value} value={option.value} data-testid={`select-preset-${option.value}`}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {value.preset === "custom" && (
        <Popover open={isCalendarOpen} onOpenChange={setIsCalendarOpen}>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              className={cn(
                "justify-start text-left font-normal",
                !value.from && "text-muted-foreground"
              )}
              data-testid="button-custom-date-range"
            >
              <CalendarIcon className="mr-2 h-4 w-4" />
              {value.from && value.to ? (
                `${format(value.from, "dd/MM/yy")} - ${format(value.to, "dd/MM/yy")}`
              ) : (
                "Seleccionar fechas"
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <Calendar
              initialFocus
              mode="range"
              defaultMonth={value.from}
              selected={{ from: value.from, to: value.to }}
              onSelect={handleDateRangeChange}
              numberOfMonths={2}
              locale={es}
            />
          </PopoverContent>
        </Popover>
      )}

      <span className="text-sm text-muted-foreground hidden sm:inline">
        {value.preset !== "custom" && (
          <>
            {format(value.from, "dd MMM", { locale: es })} - {format(value.to, "dd MMM yyyy", { locale: es })}
          </>
        )}
      </span>
    </div>
  );
}
