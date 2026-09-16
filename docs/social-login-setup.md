# Google & Apple Sign-In Setup

The code is ready. Nothing shows up on the login or register page until you
create credentials with Google and Apple and put four values in place:
two in `frontend/static/js/config.js` (public, safe to ship in the
browser), and the same two in Render's environment (used server-side to
check the token was actually issued for your app).

Until you do this, the buttons stay hidden, `initSocialAuth()` checks for
a client ID before rendering either one, so there's no broken button
sitting on the page in the meantime.

## Google (free, takes about 10 minutes)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and
   create a project if you don't already have one for Eravenda.
2. Go to **APIs & Services > OAuth consent screen**. Choose **External**,
   fill in the app name (Eravenda Market), your support email, and your
   logo if you have one. Add your live domain under authorized domains.
3. Go to **APIs & Services > Credentials**, click **Create Credentials >
   OAuth client ID**, and choose **Web application**.
4. Under **Authorized JavaScript origins**, add every origin you'll sign in
   from:
   - `https://eravenda-api.onrender.com` (or your custom domain, once you
     have one)
   - `http://localhost:8000` (for local development)
5. You don't need to add anything under **Authorized redirect URIs**, this
   flow never redirects, Google just posts a token back to your page
   directly.
6. Click Create. Copy the **Client ID** (looks like
   `123456789-abc...apps.googleusercontent.com`). You won't need the
   client secret Google also shows you, this flow doesn't use it.
7. Put that value in two places:
   - `frontend/static/js/config.js`: `window.GOOGLE_CLIENT_ID = "..."`
   - Render dashboard, your web service's Environment tab:
     `GOOGLE_CLIENT_ID`

## Apple (requires a paid Apple Developer account, $99/year)

Apple's setup has more steps than Google's, and unlike Google, it won't
work on `localhost` at all, Apple requires a real HTTPS domain for every
return URL you register. Test this one on your live Render URL, not your
local machine.

1. Go to [developer.apple.com/account](https://developer.apple.com/account)
   and enroll in the Apple Developer Program if you haven't already.
2. Under **Certificates, Identifiers & Profiles > Identifiers**, create an
   **App ID** if you don't have one for Eravenda, and enable the
   **Sign In with Apple** capability on it.
3. Still under Identifiers, click the **+** button and create a **Services
   ID**. This is the one you'll actually use as your client ID, something
   like `com.eravenda.web`. Give it a description and register it.
4. On that Services ID, enable **Sign In with Apple**, then click
   **Configure**. You'll be asked for:
   - **Primary App ID**: the App ID from step 2
   - **Domains**: your live domain, e.g. `eravenda-api.onrender.com`
   - **Return URLs**: the exact page Apple redirects back to, use
     `https://eravenda-api.onrender.com/login` (this must match the
     `redirectURI` already set in `main.js`'s `initSocialAuth()` function
     exactly, protocol and path included)
5. Save. The Services ID identifier (`com.eravenda.web` or whatever you
   named it) is your client ID.
6. Put that value in two places:
   - `frontend/static/js/config.js`: `window.APPLE_CLIENT_ID = "..."`
   - Render dashboard, your web service's Environment tab: `APPLE_CLIENT_ID`

Apple also asks you to verify domain ownership before Return URLs will
save, by hosting a verification file they give you at a specific path. Do
that step if prompted, it's part of their own flow, not something this
codebase needs to handle.

## Testing after both are set

1. Deploy with both env vars set in Render.
2. Update `config.js` with the same two values and push.
3. Visit `/login` on your live site. The Google button should render
   itself (it uses Google's own styling). The Apple button should now be
   visible instead of hidden.
4. Try signing in with an email that has never registered before, it
   should create a new buyer account and log you in immediately, same as
   a normal registration.
5. Try again with the same account, it should log you into the same
   account rather than creating a second one.
6. If you already have a password account under that same email, signing
   in with Google or Apple links the two, so you end up with one account
   you can access either way.

## What happens on the backend

Both `/api/auth/google` and `/api/auth/apple` verify the token's signature
against the provider's published public keys, check that it was issued for
your specific client ID (not someone else's app), and check the issuer.
Only after that passes does it look up or create a user. See
`backend/app/social_auth.py` for the verification logic and
`backend/app/routers/auth.py` for the account lookup/creation logic, both
short and worth reading before you consider this done.
