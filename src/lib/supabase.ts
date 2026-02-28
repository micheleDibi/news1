import { createClient } from '@supabase/supabase-js';

// Remove conflicting global type declarations
// declare global {
//   interface ImportMetaEnv {
//     PUBLIC_SUPABASE_URL: string;
//     PUBLIC_SUPABASE_ANON_KEY: string;
//   }
// }

const supabaseUrl = import.meta.env.PUBLIC_SUPABASE_URL;
const supabaseKey = import.meta.env.PUBLIC_SUPABASE_ANON_KEY;

export const supabase = createClient(supabaseUrl, supabaseKey);

// Test the connection
supabase
  .from('articles')
  .select('count', { count: 'exact' })
  .then(({ count, error }) => {
    if (error) {
      console.error('Supabase connection error:', error);
    } else {
      console.log('Connected to Supabase. Article count:', count);
    }
  });

export interface Article {
  id: number;
  title: string;
  slug: string;
  content: string;
  excerpt: string;
  image_url: string;
  audio_url?: string;
  published_at: string;
  created_at: string;
  category: string;
  category_slug: string;
  isdraft: boolean;
  creator: string;
  tags: string[];
  summary: string;
  secondary_category_slugs?: string[] | null;
  video_url?: string | null;
  video_duration?: number | null;
}

export interface Category {
  id: string;
  name: string;
  slug: string;
  description?: string;
  color: string;
  order_id?: number | null;
  keywords?: any;
}

export interface SecondaryCategory {
  id: number;
  name: string;
  slug: string;
  parent_category_slug: string;
  description?: string;
}

export interface ForumMessage {
  id: number;
  content: string;
  user_id: string;
  created_at: string;
  profiles?: {
    full_name: string;
    role: string;
  };
}

export interface Podcast {
  id: number;
  title: string;
  description: string;
  audio_url: string;
  published_at: string;
  // Optional fields
  image_url?: string;
  category?: string;
  duration?: number;
  created_at?: string;
  author_id?: string;
  featured?: boolean;
}
