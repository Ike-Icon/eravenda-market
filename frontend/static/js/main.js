/**
 * main.js
 * Small, dependency-free client-side behavior for Eravenda Market.
 * Organized as independent modules so each concern stays easy to find and edit.
 */

// ------------------------------------------------------------------
// Module: Auth
// Reads the JWT + user object the login/register pages store in
// localStorage, and exposes small helpers the other modules use.
// ------------------------------------------------------------------
const Auth = {
  getToken() {
    return localStorage.getItem("token");
  },
  getUser() {
    const raw = localStorage.getItem("user");
    return raw ? JSON.parse(raw) : null;
  },
  setSession(token, user) {
    localStorage.setItem("token", token);
    localStorage.setItem("user", JSON.stringify(user));
  },
  clearSession() {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
  },
  isLoggedIn() {
    return Boolean(this.getToken());
  },
};

// Ghana delivery locations used by checkout and store setup. The city select
// is intentionally limited to common launch markets; a user can still type a
// precise sub-town/neighbourhood below it.
const GHANA_LOCATIONS = {
  "Ahafo": ["Goaso", "Kenyasi", "Hwidiem"],
  "Ashanti": ["Kumasi", "Obuasi", "Ejisu", "Mampong"],
  "Bono": ["Sunyani", "Berekum", "Dormaa Ahenkro", "Wenchi"],
  "Bono East": ["Techiman", "Kintampo", "Atebubu"],
  "Central": ["Cape Coast", "Kasoa", "Winneba"],
  "Greater Accra": ["Accra", "Tema", "Madina", "Teshie"],
  "Eastern": ["Koforidua", "Nkawkaw", "Akosombo"],
  "Northern": ["Tamale", "Yendi", "Savelugu"],
  "Upper East": ["Bolgatanga", "Bawku", "Navrongo"],
  "Upper West": ["Wa", "Lawra", "Tumu"],
  "Volta": ["Ho", "Hohoe", "Keta"],
  "Western": ["Sekondi-Takoradi", "Tarkwa", "Axim"],
  "Western North": ["Sefwi Wiawso", "Bibiani", "Enchi"],
  "Oti": ["Dambai", "Nkwanta", "Kadjebi"],
  "North East": ["Nalerigu", "Walewale", "Gambaga"],
  "Savannah": ["Damongo", "Bole", "Salaga"],
};

function initLocationSelects(root = document) {
  root.querySelectorAll("[data-region-select]").forEach((regionSelect) => {
    const group = regionSelect.dataset.locationGroup;
    const citySelect = root.querySelector(`[data-city-select][data-location-group="${group}"]`);
    if (!citySelect || regionSelect.dataset.locationReady) return;
    const selectedRegion = regionSelect.dataset.selected || regionSelect.value;
    regionSelect.innerHTML = `<option value="">Select region</option>${Object.keys(GHANA_LOCATIONS)
      .map(region => `<option value="${region}"${region === selectedRegion ? " selected" : ""}>${region}</option>`).join("")}`;
    const populateCities = () => {
      const selectedCity = citySelect.dataset.selected || citySelect.value;
      citySelect.innerHTML = `<option value="">Select city / district</option>${(GHANA_LOCATIONS[regionSelect.value] || [])
        .map(city => `<option value="${city}"${city === selectedCity ? " selected" : ""}>${city}</option>`).join("")}`;
      citySelect.disabled = !regionSelect.value;
      citySelect.dataset.selected = "";
    };
    regionSelect.addEventListener("change", populateCities);
    populateCities();
    regionSelect.dataset.locationReady = "true";
  });
}

// ------------------------------------------------------------------
// Module: API
// Thin fetch wrapper. Same-origin now, so no CORS config to juggle.
// ------------------------------------------------------------------
async function apiFetch(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && Auth.getToken()) {
    headers["Authorization"] = `Bearer ${Auth.getToken()}`;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error((data && data.detail) || `Request failed (${res.status})`);
  }
  return res.status === 204 ? null : res.json();
}

// ------------------------------------------------------------------
// Module: Mobile navigation drawer
// ------------------------------------------------------------------
function initMobileMenu() {
  const btn = document.getElementById("mobileMenuBtn");
  const drawer = document.getElementById("mobileDrawer");
  if (!btn || !drawer) return;

  btn.addEventListener("click", () => {
    const isOpen = !drawer.classList.contains("hidden");
    drawer.classList.toggle("hidden");
    btn.setAttribute("aria-expanded", String(!isOpen));
  });
}

// ------------------------------------------------------------------
// Module: Header auth state
// The server always renders the safe "logged out" view, since the JWT
// lives in localStorage, not a cookie. This swaps in the real state
// once the page loads, and wires up the logout button.
// ------------------------------------------------------------------
function renderAuthState() {
  const guestLinks = document.getElementById("guestLinks");
  const userLinks = document.getElementById("userLinks");
  const mobileAuthLinks = document.getElementById("mobileAuthLinks");
  if (!guestLinks || !userLinks) return;

  const user = Auth.getUser();

  if (user) {
    guestLinks.classList.add("hidden");
    userLinks.classList.remove("hidden");
    userLinks.classList.add("flex");

    const firstName = document.getElementById("userFirstName");
    if (firstName) firstName.textContent = user.full_name.split(" ")[0];

    const dashboardLink = document.getElementById("dashboardLink");
    if (dashboardLink) {
      dashboardLink.href = user.role === "admin" ? "/admin/dashboard.html" : "/seller/dashboard.html";
      dashboardLink.textContent = user.role === "admin" ? "Admin" : "My store";
    }

    if (mobileAuthLinks) {
      mobileAuthLinks.innerHTML = `
        <a href="${dashboardLink ? dashboardLink.href : "/seller/dashboard.html"}" class="py-1 hover:text-brand-600">My store</a>
        <a href="/orders.html" class="py-1 hover:text-brand-600">Orders</a>
        <a href="/account" class="py-1 hover:text-brand-600">Account</a>
        <button id="mobileLogoutBtn" type="button" class="py-1 text-left hover:text-brand-600">Log out</button>
      `;
      document.getElementById("mobileLogoutBtn").addEventListener("click", logOut);
    }

    const logoutBtn = document.getElementById("logoutBtn");
    if (logoutBtn) logoutBtn.addEventListener("click", logOut);
  }
}

function logOut() {
  Auth.clearSession();
  window.location.href = "/";
}

// ------------------------------------------------------------------
// Module: Cart badge
// Fetches the live cart count so the badge is accurate even when the
// person last updated their cart on a different page or device.
// ------------------------------------------------------------------
async function refreshCartBadge() {
  const badge = document.getElementById("cartCountBadge");
  if (!badge || !Auth.isLoggedIn()) return;

  try {
    const cart = await apiFetch("/cart");
    const count = cart.items.reduce((sum, item) => sum + item.quantity, 0);
    badge.textContent = count;
    badge.classList.toggle("hidden", count === 0);
  } catch {
    // Cart badge is a nice-to-have; fail quietly rather than breaking the page.
  }
}

// ------------------------------------------------------------------
// Module: Lazy image placeholders
// Native loading="lazy" handles the deferred fetch; this just removes
// the gray placeholder background once an image actually paints, so
// there's no flash of a broken-looking box while it loads.
// ------------------------------------------------------------------
function initLazyImages() {
  document.querySelectorAll(".lazy-img img").forEach((img) => {
    if (img.complete) {
      img.closest(".lazy-img").classList.remove("animate-pulse", "bg-slate-200");
      return;
    }
    img.addEventListener("load", () => {
      img.closest(".lazy-img").classList.remove("animate-pulse", "bg-slate-200");
    });
  });
}

function initProductGallery() {
  const stage = document.querySelector("[data-product-gallery]");
  if (!stage) return;
  const image = stage.querySelector("[data-gallery-image]");
  const modal = document.getElementById("productImageModal");
  const modalImage = document.getElementById("productModalImage");
  const motionReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let hoverTimeline = null;
  const cancelHoverTimeline = () => {
    if (hoverTimeline) window.cancelAnimationFrame(hoverTimeline);
    hoverTimeline = null;
    stage.dataset.autoPanning = "";
  };
  const playHoverTimeline = () => {
    if (motionReduced) return;
    cancelHoverTimeline();
    const duration = 1200; // milliseconds: one gentle pass across the preview
    const startedAt = performance.now();
    stage.dataset.autoPanning = "true";
    const animate = (now) => {
      const progress = Math.min((now - startedAt) / duration, 1);
      const eased = progress * progress * (3 - 2 * progress);
      stage.style.setProperty("--gallery-x", `${16 - (32 * eased)}px`);
      stage.style.setProperty("--gallery-y", `${-4 + (8 * eased)}px`);
      if (progress < 1) hoverTimeline = window.requestAnimationFrame(animate);
      else stage.dataset.autoPanning = "";
    };
    hoverTimeline = window.requestAnimationFrame(animate);
  };
  const setPan = (event) => {
    cancelHoverTimeline();
    const rect = stage.getBoundingClientRect();
    const x = Math.max(-1, Math.min(1, (event.clientX - rect.left) / rect.width * 2 - 1));
    const y = Math.max(-1, Math.min(1, (event.clientY - rect.top) / rect.height * 2 - 1));
    stage.style.setProperty("--gallery-x", `${x * -18}px`);
    stage.style.setProperty("--gallery-y", `${y * -18}px`);
  };
  stage.addEventListener("pointerenter", playHoverTimeline);
  stage.addEventListener("pointerleave", () => {
    cancelHoverTimeline();
    stage.style.setProperty("--gallery-x", "0px");
    stage.style.setProperty("--gallery-y", "0px");
  });
  stage.addEventListener("pointermove", (event) => { if (event.pointerType !== "touch" || stage.hasPointerCapture(event.pointerId)) setPan(event); });
  stage.addEventListener("pointerdown", (event) => {
    stage.setPointerCapture(event.pointerId);
    stage.dataset.dragged = "";
    stage.classList.add("is-dragging");
    setPan(event);
  });
  stage.addEventListener("pointermove", (event) => {
    if (stage.hasPointerCapture(event.pointerId)) stage.dataset.dragged = "true";
  });
  stage.addEventListener("pointerup", (event) => {
    if (stage.hasPointerCapture(event.pointerId)) stage.releasePointerCapture(event.pointerId);
    stage.classList.remove("is-dragging");
    window.setTimeout(() => { stage.dataset.dragged = ""; }, 0);
  });
  document.querySelectorAll("[data-gallery-thumbnail]").forEach((button) => button.addEventListener("click", () => {
    image.src = button.dataset.imageSrc;
    if (modalImage) modalImage.src = button.dataset.imageSrc;
  }));
  const open = () => {
    if (stage.dataset.dragged === "true") return;
    if (!modal) return;
    modalImage.src = image.src;
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    document.body.classList.add("overflow-hidden");
  };
  stage.querySelector("[data-gallery-open]")?.addEventListener("click", open);
  modal?.querySelectorAll("[data-gallery-close]").forEach((button) => button.addEventListener("click", () => {
    modal.classList.add("hidden"); modal.classList.remove("flex"); document.body.classList.remove("overflow-hidden");
  }));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && modal && !modal.classList.contains("hidden")) modal.querySelector("[data-gallery-close]")?.click(); });
}

// ------------------------------------------------------------------
// Module: Newsletter signup (footer)
// No backend endpoint yet — this just gives immediate feedback so the
// form doesn't feel broken. Wire it to a real endpoint when one exists.
// ------------------------------------------------------------------
function initNewsletterForm() {
  const form = document.getElementById("newsletterForm");
  if (!form) return;

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const button = form.querySelector("button");
    const originalText = button.textContent;
    button.textContent = "Subscribed!";
    button.disabled = true;
    form.reset();
    setTimeout(() => {
      button.textContent = originalText;
      button.disabled = false;
    }, 2500);
  });
}

// ------------------------------------------------------------------
// Module: Icons
// Lucide ships as raw <i data-lucide="..."> placeholders; this call is
// what actually turns them into visible SVGs. Runs globally since the
// header's category menu uses icons on every page, not just the homepage.
// ------------------------------------------------------------------
function initIcons() {
  if (window.lucide) lucide.createIcons();
}

// ------------------------------------------------------------------
// Boot
// ------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  initMobileMenu();
  renderAuthState();
  refreshCartBadge();
  initLazyImages();
  initProductGallery();
  initNewsletterForm();
  initLocationSelects();
  initIcons();
});
