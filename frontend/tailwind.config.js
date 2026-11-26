import brand from './brand.preset.js'

/** @type {import('tailwindcss').Config} */
export default {
  // Colours, fonts and radii come from the Baimai brand tokens (brand/build_tokens.py).
  presets: [brand],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {},
  },
  plugins: [],
}
