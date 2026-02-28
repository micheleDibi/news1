import { supabase } from '../src/lib/supabase';
import { slugify } from '../src/lib/utils';

async function migrateArticleSlugs() {
  const { data: articles, error } = await supabase
    .from('articles')
    .select('*');

  if (error) {
    console.error('Error fetching articles:', error);
    return;
  }

  for (const article of articles) {
    const updates = {
      slug: slugify(article.title),
      category_slug: slugify(article.category)
    };

    const { error: updateError } = await supabase
      .from('articles')
      .update(updates)
      .eq('id', article.id);

    if (updateError) {
      console.error(`Error updating article ${article.id}:`, updateError);
    }
  }

  console.log('Migration completed');
}

migrateArticleSlugs(); 