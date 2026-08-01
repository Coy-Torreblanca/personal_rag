import { SearchView } from "@/components/search/search-view";

/**
 * `/search` route — renders the shared document search view.
 *
 * Mirrors the home page (`/`); both routes delegate to the same
 * client-side `SearchView` component so behaviour stays in sync.
 */
export default function SearchPage() {
  return <SearchView />;
}
