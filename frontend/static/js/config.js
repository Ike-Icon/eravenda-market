// Same-origin now that FastAPI serves the templates directly, so no CORS
// juggling and no hardcoded port to keep in sync.
const API_BASE = window.location.origin + "/api";

// Cloudinary unsigned upload preset, used by the seller "add product" flow.
window.CLOUDINARY_CLOUD_NAME = "ni2pcrua";
window.CLOUDINARY_UPLOAD_PRESET = "eravenda";

// Google/Apple sign-in. These are public identifiers (safe to ship in
// client code), not secrets — leave blank to hide those buttons until
// you've created the credentials. See docs/social-login-setup.md.
window.GOOGLE_CLIENT_ID = "251964652903-1uihn86jpjf80absmj90g9a6b7dpbbtn.apps.googleusercontent.com";
window.APPLE_CLIENT_ID = "";
