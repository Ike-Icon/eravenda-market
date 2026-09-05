// Thin wrapper around fetch that attaches the JWT and parses JSON.

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
    return !!this.getToken();
  },
  requireLogin(redirectTo) {
    if (!this.isLoggedIn()) {
      window.location.href = `/login?next=${encodeURIComponent(redirectTo || window.location.pathname)}`;
    }
  },
};

async function apiRequest(path, { method = "GET", body, form, auth = true } = {}) {
  const headers = {};
  if (auth && Auth.getToken()) {
    headers["Authorization"] = `Bearer ${Auth.getToken()}`;
  }

  let payload;
  if (form) {
    payload = new URLSearchParams(form);
    headers["Content-Type"] = "application/x-www-form-urlencoded";
  } else if (body !== undefined) {
    payload = JSON.stringify(body);
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${API_BASE}${path}`, { method, headers, body: payload });

  if (res.status === 204) return null;

  let data;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (!res.ok) {
    const message = (data && (data.detail || data.message)) || `Request failed (${res.status})`;
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }

  return data;
}

const Api = {
  register: (payload) => apiRequest("/auth/register", { method: "POST", body: payload, auth: false }),
  login: (email, password) =>
    apiRequest("/auth/login", { method: "POST", form: { username: email, password }, auth: false }),
  me: () => apiRequest("/auth/me"),
  addAddress: (payload) => apiRequest("/auth/addresses", { method: "POST", body: payload }),
  listAddresses: () => apiRequest("/auth/addresses"),

  listCategories: () => apiRequest("/categories", { auth: false }),
  createCategory: (payload) => apiRequest("/categories", { method: "POST", body: payload }),

  listProducts: (params = {}) => {
    const qs = new URLSearchParams(Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v != null)));
    return apiRequest(`/products?${qs.toString()}`, { auth: false });
  },
  getProduct: (id) => apiRequest(`/products/${id}`, { auth: false }),
  myProducts: () => apiRequest("/products/store/mine"),
  createProduct: (payload) => apiRequest("/products", { method: "POST", body: payload }),
  updateProduct: (id, payload) => apiRequest(`/products/${id}`, { method: "PUT", body: payload }),
  deleteProduct: (id) => apiRequest(`/products/${id}`, { method: "DELETE" }),
  addProductImage: (id, imageUrl, isPrimary) =>
    apiRequest(`/products/${id}/images?image_url=${encodeURIComponent(imageUrl)}&is_primary=${isPrimary}`, {
      method: "POST",
    }),

  createStore: (payload) => apiRequest("/stores", { method: "POST", body: payload }),
  myStore: () => apiRequest("/stores/me"),

  getCart: () => apiRequest("/cart"),
  addToCart: (productId, quantity) => apiRequest("/cart/items", { method: "POST", body: { product_id: productId, quantity } }),
  updateCartItem: (itemId, quantity) =>
    apiRequest(`/cart/items/${itemId}`, { method: "PUT", body: { product_id: "", quantity } }),
  removeCartItem: (itemId) => apiRequest(`/cart/items/${itemId}`, { method: "DELETE" }),

  checkout: (addressId) => apiRequest("/orders/checkout", { method: "POST", body: { address_id: addressId } }),
  myOrders: () => apiRequest("/orders"),
  storeOrders: () => apiRequest("/orders/store/mine"),
  updateOrderStatus: (id, status) => apiRequest(`/orders/${id}/status`, { method: "PUT", body: { status } }),

  adminStats: () => apiRequest("/admin/stats"),
  pendingStores: () => apiRequest("/admin/stores/pending"),
  approveStore: (id) => apiRequest(`/admin/stores/${id}/approve`, { method: "PUT" }),
  rejectStore: (id, reason) => apiRequest(`/admin/stores/${id}/reject`, { method: "PUT", body: { rejection_reason: reason } }),
  pendingProducts: () => apiRequest("/admin/products/pending"),
  approveProduct: (id) => apiRequest(`/admin/products/${id}/approve`, { method: "PUT" }),
  rejectProduct: (id, reason) => apiRequest(`/admin/products/${id}/reject`, { method: "PUT", body: { rejection_reason: reason } }),
};

function money(amount) {
  return `₵${Number(amount).toFixed(2)}`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}
