export default {
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
    // Library components carry their own utility classes (e.g.
    // TaskAssignmentPicker's `sm:flex-row`); the precompiled styles.css loads
    // BEFORE this app's index.css, so its media-wrapped variants lose the
    // cascade to this app's unconditioned utilities (`.flex-col`). Emitting
    // the same classes here puts the variants after the base utilities in one
    // stylesheet and the rows lay out horizontally again.
    "./node_modules/@neuronection/assistant-ui/dist/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: "#eef5ff",
          100: "#d9e8ff",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          900: "#1e3a8a",
        },
      },
    },
  },
  plugins: [],
};
