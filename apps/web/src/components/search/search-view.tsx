"use client";

import { useCallback, useState } from "react";
import { api } from "@/lib/api/client";
import type { DocumentSearchResult } from "@/lib/api/types";
import { SearchBar } from "@/components/search/search-bar";
import { SearchResults } from "@/components/search/search-results";
import { UploadButton } from "@/components/upload/upload-button";

/**
 * Shared search page body, rendered by both `/` and `/search`.
 *
 * Keeping the query/results/error state local to this single client
 * component means the two routes render identical behaviour without
 * duplicating any logic or markup.
 *
 * State model:
 * - ``results === null``  → no search has completed yet (initial or errored)
 * - ``results === []``    → search succeeded but nothing matched
 * - ``isSearching``       → an in-flight request (input is disabled meanwhile)
 * - ``error``             → human-readable message from the last failure
 */
export function SearchView() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<DocumentSearchResult[] | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Run a search and update the UI. Errors are surfaced in a banner rather
   * than thrown, so a failed request never leaves the page in a broken state.
   */
  const handleSearch = useCallback(async (q: string) => {
    setQuery(q);
    setIsSearching(true);
    setError(null);

    try {
      const data = await api.searchDocuments(q);
      setResults(data ?? []);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "An unexpected error occurred";
      setError(message);
      setResults(null);
    } finally {
      setIsSearching(false);
    }
  }, []);

  return (
    <div className="flex flex-1 flex-col items-center px-4 py-12 sm:py-24">
      {/* Upload — top-right, above the header */}
      <div className="mb-6 flex w-full max-w-2xl justify-end">
        <UploadButton />
      </div>

      {/* Header */}
      <div className="mb-8 text-center">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Search Documents
        </h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Semantic search across all your ingested documents
        </p>
      </div>

      {/* Search bar */}
      <SearchBar onSearch={handleSearch} isSearching={isSearching} />

      {/* Error banner — shown only after a failed request */}
      {error && (
        <div className="mt-6 w-full max-w-2xl rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800/40 dark:bg-red-950/30 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Results (or empty/loading placeholders) */}
      <div className="mt-8 flex w-full flex-col items-center">
        <SearchResults
          results={results}
          isSearching={isSearching}
          query={query}
        />
      </div>
    </div>
  );
}
