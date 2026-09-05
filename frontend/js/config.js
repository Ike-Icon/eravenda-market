// Same-origin now that FastAPI serves the whole site; the JSON API lives
// under /api since page routes (/, /products, etc.) now own the bare paths.
const API_BASE = window.location.origin + "/api";

// Create an unsigned upload preset in your Cloudinary dashboard
// (Settings -> Upload -> Add upload preset -> Signing mode: Unsigned)
// then fill these in so sellers can upload product photos directly
// from the browser.
const CLOUDINARY_CLOUD_NAME = "ni2pcrua";
const CLOUDINARY_UPLOAD_PRESET = "eravenda";