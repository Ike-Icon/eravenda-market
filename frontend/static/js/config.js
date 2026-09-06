// Same-origin now that FastAPI serves the templates directly, so no CORS
// juggling and no hardcoded port to keep in sync.
const API_BASE = window.location.origin + "/api";

// Cloudinary unsigned upload preset, used by the seller "add product" flow.
window.CLOUDINARY_CLOUD_NAME = "ni2pcrua";
window.CLOUDINARY_UPLOAD_PRESET = "eravenda";
