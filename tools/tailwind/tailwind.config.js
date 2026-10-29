// Settings for building frontend/static/css/tailwind.css. They mirror the
// tailwind.config block that used to sit inline in base.html. Keep the two
// in step if you change colours or fonts.
module.exports = {
  // Every file that can contain a Tailwind class name. The build keeps only the
  // classes found in these files, which is why the output is small.
  content: [
    "../../frontend/templates/**/*.html",
    "../../frontend/static/js/*.js",
    "../../backend/app/**/*.py",
  ],
  // The theme switcher sets data-theme="dark" on <html>, never a `dark` class.
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eaf5f0", 100: "#cfe9dc", 300: "#5fa886", 500: "#1c6b4f",
          600: "#17573f", 700: "#12503a", 900: "#0b2d20",
        },
        accent: { 400: "#f4b85c", 500: "#f2a93b", 600: "#c98a22" },
      },
      fontFamily: {
        head: ['"Space Grotesk"', "sans-serif"],
        body: ["Inter", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "6px", md: "6px", lg: "8px", xl: "10px", "2xl": "10px",
      },
    },
  },
};
