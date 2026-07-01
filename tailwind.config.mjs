/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    extend: {
      colors: {
        primary: '#004e9c',
        secondary: '#1a1a1a',
        offwhite: '#f5f5f5',
        sport: {
          100: '#e6f0ff',
          500: '#004e9c',
          700: '#003d7a',
          900: '#002957'
        },
        breaking: '#cc0000',
        editoriali: '#1E293B',
        cultura: '#B45309',
        lavoro: '#0D9488',
        bandi: {
          DEFAULT: '#795548',
          light: '#A1887F',
          dark: '#5D4037'
        },
        ricerca: '#0891B2',
        universita: '#1B3A7B',
        scuola: '#2D6A4F',
        tecnologia: '#2563EB',
        mondo: '#7C3AED',
        formazione: '#EA580C',
        interpelli: '#DC2626',
        'selezione-personale': '#CA8A04'
      },
      fontFamily: {
        sans: ['Poppins', 'system-ui', 'sans-serif'],
        heading: ['"League Spartan"', 'Poppins', 'sans-serif'],
        funnel: ['Poppins', 'sans-serif']
      },
      fontSize: {
        '4xl': ['2.5rem', { lineHeight: '1' }],
        '5xl': ['3rem', { lineHeight: '1' }]
      }
    },
  },
  plugins: [],
  safelist: [
    // Base colors
    'text-white',
    'text-gray-200',
    'text-gray-500',
    'text-gray-600',
    'text-gray-700',
    'text-gray-800',
    'text-gray-900',
    // Category colors with variants
    ...['sport', 'editoriali', 'cultura', 'lavoro', 'bandi', 'ricerca', 'universita', 'scuola', 'tecnologia', 'mondo', 'formazione', 'interpelli', 'selezione-personale'].flatMap(color => [
      `bg-${color}`,
      `bg-${color}-light`,
      `bg-${color}-dark`,
      `text-${color}`,
      `text-${color}-light`,
      `text-${color}-dark`,
      `ring-${color}`,
      `border-${color}`,
      `border-${color}-light`,
      `border-${color}-dark`,
      `hover:bg-${color}`,
      `hover:bg-${color}-light`,
      `hover:bg-${color}-dark`,
      `hover:text-${color}`,
      `hover:text-${color}-light`,
      `hover:text-${color}-dark`,
      `hover:border-${color}`,
      `hover:border-${color}-light`,
      `hover:border-${color}-dark`,
      `group-hover:text-${color}`,
      `group-hover:text-${color}-light`,
      `group-hover:text-${color}-dark`,
    ]),
    // Utility colors
    'text-primary',
    'text-secondary',
    'text-breaking',
    'bg-primary',
    'bg-secondary',
    'bg-breaking',
    'border-primary',
    'border-secondary',
    'border-breaking',
    // Background opacities
    'bg-black/30',
    'bg-black/40',
    'bg-black/50',
    'bg-black/60',
    'bg-black/70',
    'bg-black/80',
    // Text opacities
    'text-white/80',
    'text-gray-500/80',
    // Hover states
    'hover:bg-gray-50',
    'hover:bg-gray-100',
    'hover:text-white',
    'hover:text-gray-200',
    // Transitions
    'transition-colors',
    'transition-all',
    'duration-200',
    'duration-300'
  ]
}
