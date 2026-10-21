// ------------------------------------------------------------------
// shell.js — the mobile/desktop "shell" around every page:
//   * back button next to the mobile search bar   ([data-go-back])
//   * mobile bottom tab bar + its category sheet  (#bottomNav)
//   * floating Back-to-top / WhatsApp / Email     (#floatingActions)
// Loaded after main.js (needs Auth from it). Everything is guarded so a
// page that doesn't include a piece simply skips it.
// ------------------------------------------------------------------
(function () {
  "use strict";

  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- Back button -------------------------------------------------
  // Real history back when this visit came from our own site; otherwise
  // (opened from a shared link, new tab) go to the home page so the
  // button never dead-ends or leaves the site.
  function initGoBack() {
    document.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-go-back]");
      if (!btn) return;
      e.preventDefault();
      let sameSite = false;
      try { sameSite = !!document.referrer && new URL(document.referrer).origin === window.location.origin; } catch (_) {}
      if (sameSite && window.history.length > 1) window.history.back();
      else window.location.href = "/";
    });
  }

  // ---- Bottom nav ---------------------------------------------------
  function initBottomNav() {
    const nav = document.getElementById("bottomNav");
    if (!nav) return;

    // "Me" -> account when signed in, login when not.
    const me = document.getElementById("bottomNavMe");
    if (me && typeof Auth !== "undefined") {
      try { me.setAttribute("href", Auth.isLoggedIn() ? "/account" : "/login"); } catch (_) {}
    }

    // Avatar on the "Me" tab: the signed-in user's photo (or preset avatar). If the
    // picture is missing or fails to load, their initial letter is shown instead,
    // so a signed-in user never sees the plain guest icon. Guests see the person icon.
    function paintMeAvatar() {
      const img = document.getElementById("bottomNavMeAvatar");
      const initial = document.getElementById("bottomNavMeInitial");
      const icon = document.getElementById("bottomNavMeIcon");
      if (!img || !icon || typeof Auth === "undefined") return;
      let user = null;
      try { user = Auth.isLoggedIn() ? Auth.getUser() : null; } catch (_) {}

      const showInitial = () => {
        img.classList.add("hidden");
        if (initial) {
          initial.textContent = ((user && user.full_name) || "?").trim().charAt(0).toUpperCase();
          initial.classList.remove("hidden");
        }
      };

      if (!user) {                       // guest
        img.classList.add("hidden");
        initial && initial.classList.add("hidden");
        icon.style.display = "";
        me && me.setAttribute("aria-label", "Me");
        return;
      }
      icon.style.display = "none";
      me && me.setAttribute("aria-label", `Me, signed in as ${user.full_name || "you"}`);
      if ((user.avatar_url || user.avatar_key) && typeof userAvatarSrc === "function") {
        const src = userAvatarSrc(user, 64);
        initial && initial.classList.add("hidden");
        img.onerror = showInitial;
        if (img.getAttribute("src") !== src) img.src = src;
        img.alt = "";
        img.classList.remove("hidden");
      } else {
        showInitial();
      }
    }
    window.evRefreshBottomNavAvatar = paintMeAvatar; // called by the account page after the photo changes
    paintMeAvatar();
    window.addEventListener("storage", paintMeAvatar);

    // Category sheet
    const btn = document.getElementById("bottomNavCategoryBtn");
    const sheet = document.getElementById("bottomNavCategorySheet");
    if (!btn || !sheet) return;

    function openSheet() {
      sheet.hidden = false;
      // next frame so the slide-up transition runs
      requestAnimationFrame(() => sheet.classList.add("is-open"));
      btn.setAttribute("aria-expanded", "true");
      document.body.classList.add("overflow-hidden");
    }
    function closeSheet() {
      sheet.classList.remove("is-open");
      btn.setAttribute("aria-expanded", "false");
      document.body.classList.remove("overflow-hidden");
      setTimeout(() => { if (!sheet.classList.contains("is-open")) sheet.hidden = true; }, reduceMotion ? 0 : 260);
    }
    btn.addEventListener("click", () => (sheet.classList.contains("is-open") ? closeSheet() : openSheet()));
    sheet.querySelectorAll("[data-sheet-close]").forEach((el) => el.addEventListener("click", closeSheet));
    sheet.addEventListener("click", (e) => { if (e.target.closest("a")) closeSheet(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && sheet.classList.contains("is-open")) closeSheet(); });
    // Restored from the back/forward cache mid-close: come back with the sheet shut.
    window.addEventListener("pageshow", (e) => {
      if (!e.persisted) return;
      sheet.classList.remove("is-open");
      sheet.hidden = true;
      btn.setAttribute("aria-expanded", "false");
      document.body.classList.remove("overflow-hidden");
    });
    // Leaving the mobile layout (rotate/resize) must not leave the page locked.
    window.matchMedia("(min-width: 1024px)").addEventListener?.("change", (m) => { if (m.matches && sheet.classList.contains("is-open")) closeSheet(); });
  }

  // ---- Floating actions ----------------------------------------------
  function initFloatingActions() {
    const stack = document.getElementById("floatingActions");
    const top = document.getElementById("backToTopBtn");
    if (!stack || !top) return;

    let ticking = false;
    function update() {
      ticking = false;
      const show = window.scrollY > 400;
      stack.classList.toggle("show-top", show);
      top.tabIndex = show ? 0 : -1;
    }
    window.addEventListener("scroll", () => {
      if (!ticking) { ticking = true; requestAnimationFrame(update); }
    }, { passive: true });
    update();

    top.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
    });
  }

  // ---- Scroll reveal --------------------------------------------------
  // Elements marked data-reveal fade/slide in the first time they scroll into
  // view (CSS: ".js [data-reveal]"). Without IntersectionObserver, or with
  // reduced motion, they are simply shown.
  function initReveal() {
    const items = [...document.querySelectorAll("[data-reveal]")];
    if (!items.length) return;
    if (reduceMotion || !("IntersectionObserver" in window)) {
      items.forEach((el) => el.classList.add("is-in"));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-in");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0, rootMargin: "0px 0px -6% 0px" });
    items.forEach((el) => io.observe(el));
    // Safety net: never leave content hidden if something goes wrong.
    setTimeout(() => items.forEach((el) => el.classList.add("is-in")), 4000);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initReveal();
    initGoBack();
    initBottomNav();
    initFloatingActions();
  });
})();
