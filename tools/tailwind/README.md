# Tailwind build

The site's Tailwind CSS is built ahead of time into `frontend/static/css/tailwind.css`.
Before, every visitor's browser downloaded the Tailwind compiler (several hundred KB)
and ran it on every page. Now they download one 60 KB stylesheet (10 KB compressed)
that the browser caches for a year.

## When you must rebuild

Whenever you add or change a Tailwind class (`bg-brand-500`, `md:grid-cols-3`,
`mt-[13px]`...) in a template, a script or a Python file, or change the colours and
fonts in `tailwind.config.js`:

    tools/build-assets.sh

Then commit `frontend/static/css/tailwind.css` and `tools/tailwind/known-tokens.txt`.
If you forget, `tests/test_performance.py::test_tailwind_css_covers_every_class_in_use`
fails and names the class that is missing.

## If something looks unstyled after a deploy

Set `TAILWIND_MODE=cdn` on Render. Pages go back to compiling Tailwind in the
browser, which always sees every class. Then rebuild and switch back.
