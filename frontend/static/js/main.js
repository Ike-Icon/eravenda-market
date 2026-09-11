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

// Curated, deterministic cartoon avatars. Only the key is stored with the
// account; the URL is derived here, so users never submit arbitrary image URLs.
window.AVATAR_CHOICES = ["Avery", "Bailey", "Charlie", "Dakota", "Emery", "Finley", "Harper", "Jordan"];
window.avatarImageUrl = (key) => `https://api.dicebear.com/9.x/adventurer/svg?seed=${encodeURIComponent(key)}`;

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
// Module: Toast
// Brief, auto-dismissing status message. Keeps cart/wishlist feedback
// consistent across every page without each template reinventing it.
// ------------------------------------------------------------------
function showToast(message, type = "success") {
  let container = document.getElementById("ev-toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "ev-toast-container";
    container.className = "fixed top-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none";
    document.body.appendChild(container);
  }
  const toast = document.createElement("div");
  const colors = type === "error" ? "bg-red-600 text-white" : "bg-brand-700 text-white";
  toast.className = `pointer-events-auto px-4 py-2.5 rounded-lg shadow-lg text-sm font-medium ${colors} opacity-0 translate-y-2 transition-all duration-300`;
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => { toast.classList.remove("opacity-0", "translate-y-2"); });
  setTimeout(() => {
    toast.classList.add("opacity-0", "translate-y-2");
    setTimeout(() => toast.remove(), 300);
  }, 2200);
}

// ------------------------------------------------------------------
// Module: GuestCart
// localStorage-backed cart that works without authentication. Items
// are stored as simple product snapshots — when the user logs in,
// mergeGuestData() pushes them to the server cart and clears local
// storage so the server becomes the source of truth.
// ------------------------------------------------------------------
const CART_STORAGE_KEY = "erv_cart";

const GuestCart = {
  getItems() {
    try { return JSON.parse(localStorage.getItem(CART_STORAGE_KEY)) || []; }
    catch { return []; }
  },
  _save(items) {
    localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(items));
    this._updateBadge();
  },
  addItem(product) {
    const items = this.getItems();
    const existing = items.find(i => i.product_id === product.product_id);
    if (existing) {
      existing.quantity += product.quantity || 1;
    } else {
      items.push({
        product_id: product.product_id,
        name: product.name,
        price: product.price,
        image_url: product.image_url || "",
        quantity: product.quantity || 1,
      });
    }
    this._save(items);
  },
  removeItem(productId) {
    this._save(this.getItems().filter(i => i.product_id !== productId));
  },
  updateQuantity(productId, qty) {
    const items = this.getItems();
    const item = items.find(i => i.product_id === productId);
    if (item) { item.quantity = Math.max(1, qty); }
    this._save(items);
  },
  getCount() {
    return this.getItems().reduce((sum, i) => sum + i.quantity, 0);
  },
  getTotal() {
    return this.getItems().reduce((sum, i) => sum + (Number(i.price) * i.quantity), 0);
  },
  clear() {
    localStorage.removeItem(CART_STORAGE_KEY);
    this._updateBadge();
  },
  _updateBadge() {
    const badge = document.getElementById("cartCountBadge");
    if (!badge) return;
    const count = this.getCount();
    badge.textContent = count;
    badge.classList.toggle("hidden", count === 0);
  },
};

// ------------------------------------------------------------------
// Module: GuestWishlist
// localStorage-backed wishlist of product IDs. Same merge-on-login
// strategy as GuestCart — server becomes authoritative after sign-in.
// ------------------------------------------------------------------
const WISHLIST_STORAGE_KEY = "erv_wishlist";

const GuestWishlist = {
  getItems() {
    try { return JSON.parse(localStorage.getItem(WISHLIST_STORAGE_KEY)) || []; }
    catch { return []; }
  },
  _save(ids) {
    localStorage.setItem(WISHLIST_STORAGE_KEY, JSON.stringify(ids));
    refreshWishlistBadge();
  },
  has(productId) {
    return this.getItems().includes(productId);
  },
  toggle(productId) {
    const ids = this.getItems();
    const idx = ids.indexOf(productId);
    if (idx >= 0) { ids.splice(idx, 1); } else { ids.push(productId); }
    this._save(ids);
    return idx < 0;
  },
  add(productId) {
    const ids = this.getItems();
    if (!ids.includes(productId)) { ids.push(productId); this._save(ids); }
  },
  remove(productId) {
    this._save(this.getItems().filter(id => id !== productId));
  },
  clear() {
    localStorage.removeItem(WISHLIST_STORAGE_KEY);
    refreshWishlistBadge();
  },
  getCount() {
    return this.getItems().length;
  },
};

// ------------------------------------------------------------------
// Module: Wishlist badge
// Updates the wishlist counter badge in the header. For guests, reads
// from localStorage; for logged-in users, fetches from the server.
// ------------------------------------------------------------------
function refreshWishlistBadge() {
  const badge = document.getElementById("wishlistCountBadge");
  if (!badge) return;

  if (!Auth.isLoggedIn()) {
    const count = GuestWishlist.getCount();
    badge.textContent = count;
    badge.classList.toggle("hidden", count === 0);
    return;
  }

  apiFetch("/wishlist").then(items => {
    const count = Array.isArray(items) ? items.length : 0;
    badge.textContent = count;
    badge.classList.toggle("hidden", count === 0);
  }).catch(() => {});
}

// ------------------------------------------------------------------
// Module: Theme switcher
// Toggles between light and dark mode. Persists the choice in
// localStorage and applies it via data-theme on <html>.
// ------------------------------------------------------------------
const ThemeSwitcher = {
  get() {
    return document.documentElement.getAttribute("data-theme") || "light";
  },
  set(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("erv_theme", theme);
  },
  toggle() {
    this.set(this.get() === "dark" ? "light" : "dark");
  },
  init() {
    document.querySelectorAll("[data-theme-toggle]").forEach(el => {
      el.addEventListener("change", () => {
        this.set(el.checked ? "dark" : "light");
        document.querySelectorAll("[data-theme-toggle]").forEach(other => {
          if (other !== el) other.checked = el.checked;
        });
      });
      el.addEventListener("click", () => {
        if (el.tagName === "BUTTON") {
          this.toggle();
          document.querySelectorAll("[data-theme-toggle]").forEach(other => {
            if (other.tagName === "INPUT") other.checked = this.get() === "dark";
          });
        }
      });
    });
    document.querySelectorAll("[data-theme-toggle]").forEach(el => {
      if (el.tagName === "INPUT") el.checked = this.get() === "dark";
    });
  },
};

// ------------------------------------------------------------------
// Module: Settings
// Manages user preferences stored in localStorage: currency, density,
// notification toggles, language.
// ------------------------------------------------------------------
const UserSettings = {
  _defaults: { currency: "GHS", density: "comfortable", emailNotifs: false, pushNotifs: false, language: "en" },
  get() {
    try { return Object.assign({}, this._defaults, JSON.parse(localStorage.getItem("erv_settings")) || {}); }
    catch { return Object.assign({}, this._defaults); }
  },
  set(key, value) {
    const s = this.get();
    s[key] = value;
    localStorage.setItem("erv_settings", JSON.stringify(s));
    this._apply(s);
  },
  _apply(s) {
    document.documentElement.setAttribute("data-density", s.density || "comfortable");
    document.documentElement.setAttribute("data-currency", s.currency || "GHS");
  },
  init() {
    const s = this.get();
    this._apply(s);
    document.querySelectorAll("[data-setting]").forEach(el => {
      const key = el.dataset.setting;
      if (el.type === "checkbox") {
        el.checked = !!s[key];
        el.addEventListener("change", () => this.set(key, el.checked));
      } else if (el.tagName === "SELECT") {
        el.value = s[key] || "";
        el.addEventListener("change", () => this.set(key, el.value));
      }
    });
  },
};

// ------------------------------------------------------------------
// Module: Merge guest data on login
// After a successful login/register, push local cart items to the
// server cart and local wishlist items to the server wishlist, then
// clear localStorage so the server is the single source of truth.
// ------------------------------------------------------------------
async function mergeGuestData() {
  const localCart = GuestCart.getItems();
  for (const item of localCart) {
    try {
      await apiFetch("/cart/items", { method: "POST", body: { product_id: item.product_id, quantity: item.quantity } });
    } catch (_) { /* individual item failures shouldn't block the rest */ }
  }
  GuestCart.clear();

  const localWishlist = GuestWishlist.getItems();
  for (const productId of localWishlist) {
    try {
      await apiFetch(`/wishlist/${productId}`, { method: "POST" });
    } catch (_) { /* same reasoning */ }
  }
  GuestWishlist.clear();

  refreshCartBadge();
  refreshWishlistBadge();
  hydrateWishlistHearts();
}

// ------------------------------------------------------------------
// Module: Wishlist heart hydration
// Fills in the heart icon on every product card whose ID is already
// in the guest wishlist (or the server wishlist after login). Runs
// on page load and again after merge.
// ------------------------------------------------------------------
function hydrateWishlistHearts() {
  const isGuest = !Auth.isLoggedIn();
  document.querySelectorAll("[data-wishlist-toggle], [data-home-wishlist], [data-wishlist]").forEach(btn => {
    const productId = btn.dataset.wishlistToggle || btn.dataset.homeWishlist || btn.dataset.wishlist;
    if (!productId) return;
    const inWishlist = isGuest ? GuestWishlist.has(productId) : null;
    const icon = btn.querySelector("i");
    if (!icon) return;
    if (isGuest && inWishlist) {
      icon.className = "fas fa-heart";
    } else if (isGuest) {
      icon.className = "far fa-heart";
    }
  });
}

// ------------------------------------------------------------------
// Module: Card actions
// Wires up add-to-cart and wishlist buttons across every product
// card on the site. Uses data attributes so templates don't need
// inline scripts — just the right data-* on each button.
// ------------------------------------------------------------------
function initCardActions() {
  document.querySelectorAll("[data-cart-add]").forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "true";
    btn.addEventListener("click", async () => {
      const productId = btn.dataset.cartAdd;
      if (!Auth.isLoggedIn()) {
        GuestCart.addItem({ product_id: productId, name: btn.dataset.name || "", price: btn.dataset.price || "0", image_url: btn.dataset.image || "", quantity: 1 });
        showToast("Added to your cart");
        return;
      }
      try {
        await apiFetch("/cart/items", { method: "POST", body: { product_id: productId, quantity: 1 } });
        showToast("Added to your cart");
        refreshCartBadge();
      } catch (err) { showToast(err.message, "error"); }
    });
  });

  document.querySelectorAll("[data-wishlist-toggle]").forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "true";
    btn.addEventListener("click", async () => {
      const productId = btn.dataset.wishlistToggle;
      const icon = btn.querySelector("i");
      if (!Auth.isLoggedIn()) {
        const added = GuestWishlist.toggle(productId);
        if (icon) icon.className = added ? "fas fa-heart" : "far fa-heart";
        showToast(added ? "Added to wishlist" : "Removed from wishlist");
        return;
      }
      try {
        await apiFetch(`/wishlist/${productId}`, { method: "POST" });
        if (icon) icon.className = "fas fa-heart";
        showToast("Added to wishlist");
      } catch (err) {
        if (err.message.includes("already")) {
          await apiFetch(`/wishlist/${productId}`, { method: "DELETE" });
          if (icon) icon.className = "far fa-heart";
          showToast("Removed from wishlist");
        } else {
          showToast(err.message, "error");
        }
      }
    });
  });

  document.querySelectorAll("[data-home-cart]").forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "true";
    btn.addEventListener("click", async () => {
      const productId = btn.dataset.homeCart;
      if (!Auth.isLoggedIn()) {
        GuestCart.addItem({ product_id: productId, name: btn.dataset.name || "", price: btn.dataset.price || "0", image_url: btn.dataset.image || "", quantity: 1 });
        showToast("Added to your cart");
        return;
      }
      try {
        await apiFetch("/cart/items", { method: "POST", body: { product_id: productId, quantity: 1 } });
        btn.innerHTML = '<i class="fas fa-check"></i> Added';
        showToast("Added to your cart");
        refreshCartBadge();
      } catch (err) { showToast(err.message, "error"); }
    });
  });

  document.querySelectorAll("[data-home-wishlist]").forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "true";
    btn.addEventListener("click", async () => {
      const productId = btn.dataset.homeWishlist;
      const icon = btn.querySelector("i");
      if (!Auth.isLoggedIn()) {
        const added = GuestWishlist.toggle(productId);
        if (icon) icon.className = added ? "fas fa-heart" : "far fa-heart";
        showToast(added ? "Added to wishlist" : "Removed from wishlist");
        return;
      }
      try {
        await apiFetch(`/wishlist/${productId}`, { method: "POST" });
        if (icon) icon.className = "fas fa-heart";
        showToast("Added to wishlist");
      } catch (err) {
        if (err.message.includes("already")) {
          await apiFetch(`/wishlist/${productId}`, { method: "DELETE" });
          if (icon) icon.className = "far fa-heart";
          showToast("Removed from wishlist");
        } else {
          showToast(err.message, "error");
        }
      }
    });
  });
}

// ------------------------------------------------------------------
// Module: Mobile navigation drawer
// ------------------------------------------------------------------
function initMobileMenu() {
  const btn = document.getElementById("mobileMenuBtn");
  const drawer = document.getElementById("mobileDrawer");
  if (!btn || !drawer) return;

  const setOpen = (open) => {
    drawer.classList.toggle("hidden", !open);
    btn.setAttribute("aria-expanded", String(open));
    btn.setAttribute("aria-label", open ? "Close menu" : "Open menu");
  };

  btn.addEventListener("click", () => {
    setOpen(drawer.classList.contains("hidden"));
  });

  // Close after navigation so the next page never inherits an open drawer.
  drawer.addEventListener("click", (event) => {
    if (event.target.closest("a")) setOpen(false);
  });

  // Keep keyboard users from getting trapped in the mobile navigation.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !drawer.classList.contains("hidden")) {
      setOpen(false);
      btn.focus();
    }
  });

  // If the viewport crosses into desktop, reset the mobile state.
  window.addEventListener("resize", () => {
    if (window.innerWidth >= 1024 && !drawer.classList.contains("hidden")) {
      setOpen(false);
    }
  });
}

// ------------------------------------------------------------------
// Module: Header auth state
// The server always renders the safe "logged out" view, since the JWT
// lives in localStorage, not a cookie. This swaps in the real state
// once the page loads, and wires up the logout button.
// ------------------------------------------------------------------
async function renderAuthState() {
  const guestLinks = document.getElementById("guestLinks");
  const userLinks = document.getElementById("userLinks");
  const mobileAuthLinks = document.getElementById("mobileAuthLinks");
  if (!guestLinks || !userLinks) return;

  const user = Auth.getUser();

  if (user) {
    guestLinks.classList.add("hidden");
    userLinks.classList.remove("hidden");
    userLinks.classList.add("flex");
    initUserDropdown();

    const firstName = document.getElementById("userFirstName");
    if (firstName) firstName.textContent = user.full_name.split(" ")[0];

    const avatarImg = document.getElementById("userAvatarImg");
    const avatarFallback = document.getElementById("userAvatarFallback");
    if (avatarImg && avatarFallback) {
      if (user.avatar_key) {
        avatarImg.src = avatarImageUrl(user.avatar_key);
        avatarImg.alt = user.full_name;
        avatarImg.classList.remove("hidden");
        avatarFallback.classList.add("hidden");
      } else {
        avatarFallback.textContent = user.full_name.trim().charAt(0).toUpperCase();
        avatarFallback.classList.remove("hidden");
        avatarImg.classList.add("hidden");
      }
    }

    const navName = document.getElementById("userNavName");
    if (navName) navName.textContent = user.full_name.split(" ")[0];

    const dashboardLink = document.getElementById("dashboardLink");
    const professionalDashboardLink = document.getElementById("professionalDashboardLink");
    const hasDashboard = user.role === "admin" || user.role === "seller";
    if (dashboardLink) {
      if (hasDashboard) {
        dashboardLink.href = user.role === "admin" ? "/admin/dashboard.html" : "/seller/dashboard.html";
        const icon = dashboardLink.querySelector("i");
        const span = dashboardLink.querySelector("span");
        if (user.role === "admin") {
          if (icon) icon.className = "ev-nav-icon-green fas fa-gauge-high w-4 text-center";
          if (span) span.textContent = "Admin Dashboard";
        } else {
          if (icon) icon.className = "ev-nav-icon-green fas fa-store w-4 text-center";
          if (span) span.textContent = "My Store";
        }
        dashboardLink.style.display = "";
      } else {
        dashboardLink.style.display = "none";
      }
    }

    let hasProfessionalProfile = false;
    try {
      const profile = await apiFetch('/services/me');
      hasProfessionalProfile = !!profile;
    } catch (_) {
      hasProfessionalProfile = false;
    }
    if (professionalDashboardLink) {
      professionalDashboardLink.style.display = hasProfessionalProfile ? "" : "none";
    }

    if (mobileAuthLinks) {
      const roleLink = hasDashboard
        ? `<a href="${dashboardLink.href}" class="py-2 px-2 hover:bg-brand-50 rounded-lg">${dashboardLink.querySelector("span")?.textContent || "Dashboard"}</a>`
        : `<a href="/account#seller-application" class="py-2 px-2 hover:bg-brand-50 rounded-lg">Become a Seller</a>`;
      const professionalLink = hasProfessionalProfile
        ? `<a href="/professional/dashboard.html" class="py-2 px-2 hover:bg-brand-50 rounded-lg"><i class="fas fa-briefcase text-accent-600 mr-2"></i>Pro Dashboard</a>`
        : `<a href="/services/register" class="py-2 px-2 hover:bg-brand-50 rounded-lg"><i class="fas fa-user-plus text-accent-600 mr-2"></i>Join as a Handyman</a>`;
      mobileAuthLinks.innerHTML = `
        ${roleLink}
        <a href="/orders.html" class="py-1 hover:text-brand-600">Orders</a>
        <a href="/services" class="py-1 text-brand-700"><i class="fas fa-screwdriver-wrench text-brand-500 mr-2"></i>Handyman Hub</a>
        <a href="/services" class="pl-6 py-1 hover:text-brand-600">Hire a Handyman</a>
        <a href="/services/register" class="pl-6 py-1 hover:text-brand-600">Join as a Handyman</a>
        <a href="/account" class="py-1 hover:text-brand-600">Account</a>
        <button id="mobileLogoutBtn" type="button" class="py-1 text-left hover:text-brand-600">Log out</button>
      `;
      document.getElementById("mobileLogoutBtn").addEventListener("click", logOut);
    }

    const logoutBtn = document.getElementById("logoutBtn");
    if (logoutBtn) logoutBtn.addEventListener("click", logOut);

    refreshWishlistBadge();
  }
}

function initUserDropdown() {
  const btn = document.getElementById("userMenuBtn");
  const dropdown = document.getElementById("userDropdown");
  if (!btn || !dropdown || btn.dataset.bound) return;
  btn.dataset.bound = "true";

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = !dropdown.classList.contains("hidden");
    dropdown.classList.toggle("hidden", isOpen);
    btn.setAttribute("aria-expanded", String(!isOpen));
  });

  document.addEventListener("click", (e) => {
    if (!dropdown.classList.contains("hidden") && !dropdown.contains(e.target) && !btn.contains(e.target)) {
      dropdown.classList.add("hidden");
      btn.setAttribute("aria-expanded", "false");
    }
  });

  dropdown.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      dropdown.classList.add("hidden");
      btn.setAttribute("aria-expanded", "false");
      btn.focus();
    }
  });
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
  if (!badge) return;

  if (!Auth.isLoggedIn()) {
    GuestCart._updateBadge();
    return;
  }

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
// Module: Password visibility toggle
// Wraps every password input with an eye icon button that flips the
// field between hidden and plain text. Runs globally so login,
// register, reset-password and account forms all get it for free.
// ------------------------------------------------------------------
function initPasswordToggles() {
  document.querySelectorAll('input[type="password"]').forEach((input) => {
    if (input.dataset.toggleWrapped) return;
    input.dataset.toggleWrapped = "true";

    const wrapper = document.createElement("div");
    wrapper.className = "relative";
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    input.classList.add("pr-10");

    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-label", "Show password");
    button.tabIndex = -1;
    button.className = "absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-600";
    button.innerHTML = '<i data-lucide="eye" class="w-4 h-4"></i>';

    button.addEventListener("click", () => {
      const nowShowing = input.type === "password";
      input.type = nowShowing ? "text" : "password";
      button.setAttribute("aria-label", nowShowing ? "Hide password" : "Show password");
      button.innerHTML = `<i data-lucide="${nowShowing ? "eye-off" : "eye"}" class="w-4 h-4"></i>`;
      if (window.lucide) lucide.createIcons();
    });

    wrapper.appendChild(button);
  });
  if (window.lucide) lucide.createIcons();
}

// ------------------------------------------------------------------
// Module: Category strip slider
// The category bar scrolls horizontally instead of wrapping. This wires
// the prev/next arrow buttons to page it, and shows/hides each arrow
// depending on whether there's more to scroll in that direction.
// ------------------------------------------------------------------
function initCategoryStrip() {
  const strip = document.getElementById("categoryStrip");
  const prevBtn = document.getElementById("categoryStripPrev");
  const nextBtn = document.getElementById("categoryStripNext");
  if (!strip || !prevBtn || !nextBtn) return;

  const updateArrows = () => {
    const maxScroll = strip.scrollWidth - strip.clientWidth;
    const atStart = strip.scrollLeft <= 4;
    const atEnd = strip.scrollLeft >= maxScroll - 4;
    prevBtn.classList.toggle("hidden", atStart);
    prevBtn.classList.toggle("flex", !atStart);
    nextBtn.classList.toggle("hidden", maxScroll <= 4 || atEnd);
    nextBtn.classList.toggle("flex", maxScroll > 4 && !atEnd);
  };

  const page = (direction) => {
    strip.scrollBy({ left: direction * strip.clientWidth * 0.8, behavior: "smooth" });
  };

  prevBtn.addEventListener("click", () => page(-1));
  nextBtn.addEventListener("click", () => page(1));
  strip.addEventListener("scroll", updateArrows);
  window.addEventListener("resize", updateArrows);
  updateArrows();
}

// ------------------------------------------------------------------
// Module: Category subcategory dropdowns
// Each parent category's subcategories live in a <template>, kept
// outside the horizontally-scrolling strip. Clicking a parent's chevron
// clones its template into the single shared panel and positions the
// panel with the clicked button's own coordinates — that's what keeps
// it visible instead of being clipped by the strip's overflow-x-auto.
// ------------------------------------------------------------------
function initCategoryDropdowns() {
  const panel = document.getElementById("categoryDropdownPanel");
  const strip = document.getElementById("categoryStrip");
  if (!panel || !strip) return;

  let openToggle = null;
  let closeTimer = null;

  const cancelClose = () => {
    if (closeTimer) {
      clearTimeout(closeTimer);
      closeTimer = null;
    }
  };

  const closeDropdown = () => {
    cancelClose();
    panel.classList.add("hidden");
    panel.innerHTML = "";
    if (openToggle) {
      openToggle.setAttribute("aria-expanded", "false");
      openToggle.querySelector("i")?.classList.remove("rotate-180");
    }
    openToggle = null;
  };

  const scheduleClose = () => {
    cancelClose();
    closeTimer = setTimeout(closeDropdown, 120);
  };

  const positionPanel = (toggle) => {
    const rect = toggle.getBoundingClientRect();
    panel.style.top = `${rect.bottom}px`;

    // Position from the category, then keep the menu inside the viewport.
    panel.style.left = `${Math.max(8, rect.left)}px`;
    panel.style.right = "auto";

    requestAnimationFrame(() => {
      const panelRect = panel.getBoundingClientRect();
      const rightOverflow = panelRect.right - window.innerWidth + 8;
      if (rightOverflow > 0) {
        panel.style.left = `${Math.max(8, rect.left - rightOverflow)}px`;
      }
    });
  };

  const openDropdown = (toggle) => {
    cancelClose();
    const wasOpen = toggle === openToggle;

    if (wasOpen && !panel.classList.contains("hidden")) return;

    closeDropdown();

    const template = document.getElementById(`cat-children-${toggle.dataset.catId}`);
    if (!template) return;

    panel.innerHTML = "";
    panel.appendChild(template.content.cloneNode(true));
    panel.classList.remove("hidden");
    positionPanel(toggle);

    toggle.setAttribute("aria-expanded", "true");
    toggle.querySelector("i")?.classList.add("rotate-180");
    openToggle = toggle;

    if (window.lucide) lucide.createIcons();
  };

  strip.querySelectorAll(".cat-dropdown-toggle").forEach((toggle) => {
    const item = toggle.closest(".shrink-0");
    if (!item) return;

    // Hovering anywhere over the category opens its subcategory menu.
    item.addEventListener("mouseenter", () => openDropdown(toggle));
    item.addEventListener("mouseleave", scheduleClose);

    // Keep click support for touch devices and keyboard users.
    toggle.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();

      if (toggle === openToggle && !panel.classList.contains("hidden")) {
        closeDropdown();
      } else {
        openDropdown(toggle);
      }
    });

    toggle.addEventListener("focus", () => openDropdown(toggle));
    toggle.addEventListener("blur", scheduleClose);
  });

  // Moving from a category into its dropdown should not close the menu.
  panel.addEventListener("mouseenter", cancelClose);
  panel.addEventListener("mouseleave", scheduleClose);

  document.addEventListener("click", (e) => {
    if (openToggle && !panel.contains(e.target) && !strip.contains(e.target)) {
      closeDropdown();
    }
  });

  strip.addEventListener("scroll", closeDropdown);
  window.addEventListener("resize", closeDropdown);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDropdown();
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
  refreshWishlistBadge();
  initLazyImages();
  initProductGallery();
  initNewsletterForm();
  initLocationSelects();
  initIcons();
  initPasswordToggles();
  initCategoryStrip();
  initCategoryDropdowns();
  initCardActions();
  hydrateWishlistHearts();
  ThemeSwitcher.init();
  UserSettings.init();
});
