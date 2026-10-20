// ------------------------------------------------------------------
// avatar-cropper.js: a small, dependency-free photo cropper.
//
//   const blob = await openAvatarCropper(file);   // Blob (JPEG), or null if cancelled
//
// Opens a dialog with a square stage and a circular guide. The person can
// drag to reposition, zoom (slider, +/- buttons, mouse wheel, pinch), rotate in
// 90 degree steps, and reset. "Use this photo" returns a 512x512 JPEG of exactly
// what is inside the circle. Nothing is uploaded here; the caller does that.
// Keyboard: arrow keys move, + / - zoom, Esc cancels.
// ------------------------------------------------------------------
(function () {
  "use strict";

  const OUTPUT = 512;        // exported size in px (square)
  const MAX_SOURCE = 2048;   // big phone photos are shrunk to this before editing, to keep dragging smooth
  const MAX_ZOOM = 4;

  function openAvatarCropper(file) {
    return new Promise((resolve) => {
      const url = URL.createObjectURL(file);
      const image = new Image();
      image.onload = () => start(image, url);
      image.onerror = () => {
        URL.revokeObjectURL(url);
        if (typeof showToast === "function") showToast("That file couldn't be opened as a picture. Try a JPG, PNG or WebP.", "error");
        resolve(null);
      };
      image.src = url;

      function start(img, objectUrl) {
        // Shrink very large photos once up front.
        let source = img;
        let iw = img.naturalWidth, ih = img.naturalHeight;
        if (Math.max(iw, ih) > MAX_SOURCE) {
          const k = MAX_SOURCE / Math.max(iw, ih);
          const c = document.createElement("canvas");
          c.width = Math.round(iw * k); c.height = Math.round(ih * k);
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          source = c; iw = c.width; ih = c.height;
        }
        URL.revokeObjectURL(objectUrl);

        const previouslyFocused = document.activeElement;
        const V = Math.max(220, Math.min(320, window.innerWidth - 64)); // stage size in CSS px
        const dpr = Math.min(window.devicePixelRatio || 1, 2);

        const root = document.createElement("div");
        root.className = "ev-crop";
        root.setAttribute("role", "dialog");
        root.setAttribute("aria-modal", "true");
        root.setAttribute("aria-labelledby", "evCropTitle");
        root.innerHTML = `
          <div class="ev-crop-backdrop" data-crop-cancel></div>
          <div class="ev-crop-panel">
            <h2 id="evCropTitle" class="ev-crop-title">Crop your photo</h2>
            <p class="ev-crop-hint">Drag to move. Pinch, scroll or use the slider to zoom.</p>
            <div class="ev-crop-stage" style="width:${V}px;height:${V}px">
              <canvas tabindex="0" aria-label="Photo crop area. Arrow keys move the photo, plus and minus zoom."></canvas>
            </div>
            <div class="ev-crop-controls">
              <button type="button" class="ev-crop-icon" data-rotate="-90" aria-label="Rotate left"><i class="fas fa-rotate-left" aria-hidden="true"></i></button>
              <button type="button" class="ev-crop-icon" data-zoom-step="-0.25" aria-label="Zoom out"><i class="fas fa-minus" aria-hidden="true"></i></button>
              <input type="range" min="1" max="${MAX_ZOOM}" step="0.01" value="1" aria-label="Zoom">
              <button type="button" class="ev-crop-icon" data-zoom-step="0.25" aria-label="Zoom in"><i class="fas fa-plus" aria-hidden="true"></i></button>
              <button type="button" class="ev-crop-icon" data-rotate="90" aria-label="Rotate right"><i class="fas fa-rotate-right" aria-hidden="true"></i></button>
            </div>
            <div class="ev-crop-actions">
              <button type="button" class="ev-crop-btn" data-crop-cancel>Cancel</button>
              <button type="button" class="ev-crop-btn" data-crop-reset>Reset</button>
              <button type="button" class="ev-crop-btn ev-crop-primary" data-crop-save>Use this photo</button>
            </div>
          </div>`;
        document.body.appendChild(root);
        document.body.classList.add("overflow-hidden");

        const canvas = root.querySelector("canvas");
        canvas.width = Math.round(V * dpr); canvas.height = Math.round(V * dpr);
        canvas.style.width = V + "px"; canvas.style.height = V + "px";
        const ctx = canvas.getContext("2d");
        const slider = root.querySelector('input[type="range"]');

        // ---- state: rotation (multiples of 90), zoom (1 = photo just covers the circle), offset in stage px
        let rot = 0, zoom = 1, ox = 0, oy = 0;

        const rotated = () => (rot % 180 === 0 ? { w: iw, h: ih } : { w: ih, h: iw });
        const baseScale = () => { const d = rotated(); return Math.max(V / d.w, V / d.h); };
        function clampOffset() {
          const d = rotated(); const s = baseScale() * zoom;
          const maxX = Math.max(0, (d.w * s - V) / 2), maxY = Math.max(0, (d.h * s - V) / 2);
          ox = Math.min(maxX, Math.max(-maxX, ox));
          oy = Math.min(maxY, Math.max(-maxY, oy));
        }
        function setZoom(z) {
          zoom = Math.min(MAX_ZOOM, Math.max(1, z));
          slider.value = String(zoom);
          clampOffset(); draw();
        }

        // Paint the photo into a ctx whose coordinate space is `size` px square.
        function paintPhoto(c, size) {
          const k = size / V;
          c.save();
          c.translate(size / 2 + ox * k, size / 2 + oy * k);
          c.rotate((rot * Math.PI) / 180);
          const s = baseScale() * zoom * k;
          c.scale(s, s);
          c.drawImage(source, -iw / 2, -ih / 2);
          c.restore();
        }
        function draw() {
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          ctx.fillStyle = "#111827";
          ctx.fillRect(0, 0, V, V);
          paintPhoto(ctx, V);
          // dim everything outside the circle, then outline it
          ctx.fillStyle = "rgba(0,0,0,.55)";
          ctx.beginPath();
          ctx.rect(0, 0, V, V);
          ctx.arc(V / 2, V / 2, V / 2 - 3, 0, Math.PI * 2, true);
          ctx.fill("evenodd");
          ctx.strokeStyle = "rgba(255,255,255,.95)";
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(V / 2, V / 2, V / 2 - 3, 0, Math.PI * 2);
          ctx.stroke();
        }

        // ---- pointer: one finger/mouse drags, two fingers pinch
        const pointers = new Map();
        let pinchStart = null;
        canvas.addEventListener("pointerdown", (e) => {
          canvas.setPointerCapture(e.pointerId);
          pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
          if (pointers.size === 2) {
            const [a, b] = [...pointers.values()];
            pinchStart = { dist: Math.hypot(a.x - b.x, a.y - b.y), zoom };
          }
          canvas.classList.add("is-grabbing");
        });
        canvas.addEventListener("pointermove", (e) => {
          const p = pointers.get(e.pointerId);
          if (!p) return;
          if (pointers.size === 1) {
            ox += e.clientX - p.x; oy += e.clientY - p.y;
            clampOffset(); draw();
          }
          p.x = e.clientX; p.y = e.clientY;
          if (pointers.size === 2 && pinchStart) {
            const [a, b] = [...pointers.values()];
            const dist = Math.hypot(a.x - b.x, a.y - b.y);
            if (pinchStart.dist > 0) setZoom(pinchStart.zoom * (dist / pinchStart.dist));
          }
        });
        const endPointer = (e) => {
          pointers.delete(e.pointerId);
          if (pointers.size < 2) pinchStart = null;
          if (!pointers.size) canvas.classList.remove("is-grabbing");
        };
        canvas.addEventListener("pointerup", endPointer);
        canvas.addEventListener("pointercancel", endPointer);
        canvas.addEventListener("wheel", (e) => {
          e.preventDefault();
          setZoom(zoom * (e.deltaY < 0 ? 1.08 : 0.92));
        }, { passive: false });

        // ---- controls
        slider.addEventListener("input", () => setZoom(parseFloat(slider.value)));
        root.querySelectorAll("[data-zoom-step]").forEach((b) => b.addEventListener("click", () => setZoom(zoom + parseFloat(b.dataset.zoomStep))));
        root.querySelectorAll("[data-rotate]").forEach((b) => b.addEventListener("click", () => {
          rot = (rot + parseInt(b.dataset.rotate, 10) + 360) % 360;
          ox = 0; oy = 0; clampOffset(); draw();
        }));
        root.querySelector("[data-crop-reset]").addEventListener("click", () => { rot = 0; ox = 0; oy = 0; setZoom(1); });

        canvas.addEventListener("keydown", (e) => {
          const step = 12;
          const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
          if (moves[e.key]) { e.preventDefault(); ox += moves[e.key][0]; oy += moves[e.key][1]; clampOffset(); draw(); }
          else if (e.key === "+" || e.key === "=") { e.preventDefault(); setZoom(zoom + 0.15); }
          else if (e.key === "-" || e.key === "_") { e.preventDefault(); setZoom(zoom - 0.15); }
        });

        // ---- finish
        let done = false;
        function close(result) {
          if (done) return;
          done = true;
          document.removeEventListener("keydown", onKey, true);
          root.remove();
          document.body.classList.remove("overflow-hidden");
          if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
          resolve(result);
        }
        root.querySelectorAll("[data-crop-cancel]").forEach((el) => el.addEventListener("click", () => close(null)));
        root.querySelector("[data-crop-save]").addEventListener("click", () => {
          const out = document.createElement("canvas");
          out.width = OUTPUT; out.height = OUTPUT;
          const oc = out.getContext("2d");
          oc.fillStyle = "#ffffff";            // JPEG has no transparency
          oc.fillRect(0, 0, OUTPUT, OUTPUT);
          paintPhoto(oc, OUTPUT);
          out.toBlob((blob) => close(blob), "image/jpeg", 0.9);
        });

        function onKey(e) {
          if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(null); return; }
          if (e.key !== "Tab") return;
          // keep Tab inside the dialog
          const focusable = [...root.querySelectorAll("button, input, canvas[tabindex]")].filter((el) => !el.disabled);
          if (!focusable.length) return;
          const first = focusable[0], last = focusable[focusable.length - 1];
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
        document.addEventListener("keydown", onKey, true);

        draw();
        canvas.focus();
      }
    });
  }

  window.openAvatarCropper = openAvatarCropper;
})();
