/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Geist', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['Fraunces', 'Georgia', 'serif'],
        mono: ['"Geist Mono"', '"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      letterSpacing: {
        'editorial': '0.18em',
      },
      colors: {
        // Warm research-benchmark palette (agenthle.org dna)
        cream: '#f7f5f2',    // page background
        paper: '#EEEDE6',    // subtle surface accent
        seam:  '#E4E4E0',    // hairline border
        ink:   '#0b0b0a',    // primary text
      },
    },
  },
  plugins: [],
}
