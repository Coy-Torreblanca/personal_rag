import { SearchView } from "@/components/search/search-view";

/**
 * Home page — renders the shared document search view.
 *
 * This is a server component that delegates all interactive behaviour
 * (query state, API calls, error handling) to the client-side
 * `SearchView`, keeping the route itself static and fast to render.
 */
export default function HomePage() {
  return <SearchView />;
}
