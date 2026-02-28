import { supabase, type Category } from './supabase';

// Export the array binding - it will be updated in place
export let categories: Category[] = [];

// Flag to prevent multiple initial fetches
let isFetching = false;
let initialFetchDone = false;

// Function to fetch and update the exported array *in place*
async function fetchAndUpdateExportedArray(): Promise<void> {
  if (isFetching) return; // Prevent concurrent fetches
  isFetching = true;
  console.log('Fetching/Refreshing categories from Supabase...');

  try {
    const { data, error } = await supabase
      .from('categories') 
      .select('id, name, slug, color, order_id, keywords, description')
      .order('order_id', { ascending: true, nullsFirst: false })
      .order('name', { ascending: true });

    if (error) {
      console.error('CRITICAL: Error fetching categories:', error);
      // Keep the old data if fetch fails after initial load?
      // Or clear it? For now, log error and potentially keep stale data.
    } else if (data) {
      const newCategories = data.map(cat => ({
          id: String(cat.id), 
          name: cat.name,
          slug: cat.slug,
          color: cat.color,
          keywords: cat.keywords,
          description: cat.description
      })) as Category[];
      
      // Sort logic is now handled by the Supabase query's .order()
      
      // --- Update the exported array IN PLACE --- 
      categories.length = 0; // Clear the array without changing the reference
      categories.push(...newCategories); // Add new items
      // ----------------------------------------
      
      console.log(`Categories array updated. Count: ${categories.length}`);
      initialFetchDone = true; // Mark initial fetch as complete
    } else {
      console.warn('No categories data returned from Supabase during fetch/refresh.');
      if (!initialFetchDone) {
        categories.length = 0; // Ensure empty if first fetch fails
      }
    }
  } catch (err) {
    console.error('CRITICAL: Exception during category fetch/update:', err);
  } finally {
    isFetching = false;
  }
}

// --- Perform initial fetch --- 
// (Runs when module loads, but doesn't block export)
fetchAndUpdateExportedArray();
// ---------------------------

// Export the function to allow external refresh triggers
export { fetchAndUpdateExportedArray as refreshCategories };

// Keep synchronous getters - they operate on the (potentially updating) exported array
export function getCategoryBySlug(slug: string): Category | undefined {
  // Add a check/warning if accessed before initial fetch?
  // if (!initialFetchDone) console.warn('getCategoryBySlug called before initial fetch complete');
  return categories.find(category => category.slug === slug.toLowerCase());
}

export function getCategoryByName(name: string): Category | undefined {
  // if (!initialFetchDone) console.warn('getCategoryByName called before initial fetch complete');
  return categories.find(category => category.name === name);
} 