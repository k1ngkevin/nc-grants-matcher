import { useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/** Searchable agency dropdown (type "DEQ" or "environment"). */
export default function AgencyPicker({ agencies, value, onChange, id, placeholder = "Choose your agency", className, autoFocus }) {
  const [open, setOpen] = useState(false);
  const selected = agencies.find((a) => a.id === value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button id={id} variant="outline" role="combobox" aria-expanded={open} autoFocus={autoFocus}
          className={cn("h-11 w-full justify-between bg-white px-3 text-left font-normal", !selected && "text-muted-foreground", className)}>
          <span className="truncate">{selected ? `${selected.name} (${selected.short})` : placeholder}</span>
          <ChevronsUpDown className="opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) min-w-72 p-0" align="start">
        <Command filter={(itemValue, search) => (itemValue.toLowerCase().includes(search.toLowerCase()) ? 1 : 0)}>
          <CommandInput placeholder="Search by name or abbreviation" />
          <CommandList className="max-h-80">
            <CommandEmpty>No agency matches that.</CommandEmpty>
            {agencies.map((a) => (
              <CommandItem key={a.id} value={`${a.name} ${a.short}`} onSelect={() => { onChange(a.id); setOpen(false); }}>
                <span className="flex-1">{a.name}</span>
                <span className="text-xs text-muted-foreground">{a.short}</span>
                <Check className={cn("ml-1", a.id === value ? "opacity-100" : "opacity-0")} />
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

/** Small ridgeline mark used in the header. */
export function RidgeMark({ className }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
      <rect width="32" height="32" rx="7" fill="#ffffff" />
      <path d="M3 23 L10 14 L14 18 L20 10 L29 21 L29 26 L3 26 Z" fill="#7b9db2" />
      <path d="M3 26 L9 20 L14 23 L21 16 L29 24 L29 26 Z" fill="#1f5a45" />
    </svg>
  );
}
