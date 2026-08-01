"use client";

import { useState, type FormEvent, type KeyboardEvent } from "react";
import { Search, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface SearchBarProps {
  onSearch: (query: string) => void;
  isSearching?: boolean;
  placeholder?: string;
  className?: string;
}

export function SearchBar({
  onSearch,
  isSearching = false,
  placeholder = "Search your documents…",
  className,
}: SearchBarProps) {
  const [query, setQuery] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed) onSearch(trimmed);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const trimmed = query.trim();
      if (trimmed) onSearch(trimmed);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className={cn("relative flex w-full max-w-2xl items-center gap-2", className)}
    >
      <div className="relative flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isSearching}
          className="h-11 pl-10 pr-4 text-base"
        />
      </div>
      <Button
        type="submit"
        disabled={isSearching || !query.trim()}
        size="lg"
        className="h-11 shrink-0"
      >
        {isSearching ? (
          <>
            <Loader2 className="size-4 animate-spin" />
            Searching…
          </>
        ) : (
          "Search"
        )}
      </Button>
    </form>
  );
}
