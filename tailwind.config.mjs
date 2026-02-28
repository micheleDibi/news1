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
        calcio: {
          DEFAULT: '#4CAF50',
          light: '#81C784',
          dark: '#388E3C'
        },
        motori: {
          DEFAULT: '#A55800',
          light: '#C07000',
          dark: '#8A4700'
        },
        tennis: {
          DEFAULT: '#1A78C2',
          light: '#4A9CF5',
          dark: '#135EA0'
        },
        basket: {
          DEFAULT: '#9C27B0',
          light: '#BA68C8',
          dark: '#7B1FA2'
        },
        editoriali: '#616161',
        commenti: {
          DEFAULT: '#E91E63',
          light: '#F06292',
          dark: '#C2185B'
        },
        cultura: '#8E44AD',
        lavoro: '#3E4A61',
        bandi: {
          DEFAULT: '#795548',
          light: '#A1887F',
          dark: '#5D4037'
        },
        ricerca: '#137177',
        universita:'#2F7D31',
        scuola: '#F4B400',
        tecnologia:'#3A01A2',
        mondo: '#03A9F4',
        formazione:'#FB8C00'
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        funnel: ['"Funnel Sans"', 'sans-serif'],
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
    ...['calcio', 'motori', 'tennis', 'basket', 'sport', 'editoriali', 'commenti', 'cultura', 'lavoro', 'bandi','ricerca', 'universita', 'scuola', 'tecnologia', 'mondo','formazione'].flatMap(color => [
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


