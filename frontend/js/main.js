// Wires up the header: auth-aware links, cart badge, search form, logout.

function initHeader() {
  const actions = document.getElementById("headerActions");
  if (!actions) return;

  const user = Auth.getUser();

  if (user) {
    const sellerLink = user.role === "seller"
      ? `<a href="/seller/dashboard.html">My store</a>`
      : `<a href="/seller/dashboard.html">Sell on Eravenda Market</a>`;
    const adminLink = user.role === "admin" ? `<a href="/admin/dashboard.html">Admin</a>` : "";

    actions.innerHTML = `
      ${adminLink}
      ${sellerLink}
      <a href="/orders.html">Orders</a>
      <a href="/cart" class="cart-link">Cart <span id="cartCount" class="cart-count" style="display:none">0</span></a>
      <a href="#" id="logoutBtn">Log out (${escapeHtml(user.full_name.split(" ")[0])})</a>
    `;
    document.getElementById("logoutBtn").addEventListener("click", (e) => {
      e.preventDefault();
      Auth.clearSession();
      window.location.href = "/";
    });
    refreshCartCount();
  } else {
    actions.innerHTML = `
      <a href="/login">Log in</a>
      <a href="/register">Sign up</a>
      <a href="/cart" class="cart-link">Cart</a>
    `;
  }

  const searchForm = document.getElementById("searchForm");
  if (searchForm) {
    searchForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const q = searchForm.querySelector("input[name=q]").value.trim();
      window.location.href = `/products?q=${encodeURIComponent(q)}`;
    });
  }
}

async function refreshCartCount() {
  const badge = document.getElementById("cartCount");
  if (!badge || !Auth.isLoggedIn()) return;
  try {
    const cart = await Api.getCart();
    const count = cart.items.reduce((sum, item) => sum + item.quantity, 0);
    if (count > 0) {
      badge.textContent = count;
      badge.style.display = "inline-block";
    }
  } catch {
    // not fatal if this fails silently
  }
}

document.addEventListener("DOMContentLoaded", initHeader);
