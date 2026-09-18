/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#111827',
        maroon: '#912338', // Concordia's crimson
      },
    },
  },
  plugins: [],
}
