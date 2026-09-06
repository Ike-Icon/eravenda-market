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
  initNewsletterForm();
  initIcons();
});
