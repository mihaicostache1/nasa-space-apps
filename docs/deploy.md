# Deploy: Render (API) + Vercel (web)

The demo needs no NASA access at runtime. The API image contains the archived, checksummed reference bundle, and the web app only calls that API. Deploy the API first, because the web build needs its URL.

## 1. API on Render

1. In Render, choose **New → Blueprint** and connect this GitHub repository. Render reads `render.yaml` and proposes the `lunarwindow-api` web service:
   - built with Docker from `backend/Dockerfile`;
   - the last stage, `api`, is what gets built;
   - free plan, health check `/api/health`, `PORT=8000`.
2. When prompted for `LUNARWINDOW_CORS_ORIGINS`, enter the web origin you will use, for example `https://lunarwindow.vercel.app`.
   - The value is a comma-separated list, with no trailing slashes.
   - You can change it later under the service's **Environment** tab.
3. Deploy. When the service is live, check it:

   ```sh
   curl https://<your-api>.onrender.com/api/health
   curl https://<your-api>.onrender.com/api/reference/sites
   ```

   `/api/reference/sites` should list three verified reference points covering 2026-11-14 to 2026-12-14.

## 2. Web on Vercel

1. In Vercel, choose **Add New → Project** and import the same repository.
   - Framework: Next.js, detected automatically.
   - Root directory: the repository root.
   - Build command: the default `npm run build`.
2. Under **Environment Variables**, add `NEXT_PUBLIC_API_BASE_URL` = `https://<your-api>.onrender.com`, with no trailing slash.
   - Next.js inlines it into the browser bundle at build time.
   - Changing it later requires a **Redeploy**.
3. Deploy, then open the production URL. The page should load the reference sites and show both scenarios.

If the Vercel production domain differs from what you entered in step 1.2, update `LUNARWINDOW_CORS_ORIGINS` on Render to match. Preview deployments get their own URLs, which CORS does not allow unless you add them.

## Before a live demo

- **Wake the API.** Render's free plan sleeps after about 15 minutes without traffic, and the first request then takes up to a minute. Open `https://<your-api>.onrender.com/api/health` a few minutes before presenting. If the page shows "Cannot reach the LunarWindow API", wait and press **Retry**.
- **Test in a clean browser.** Use a private window on a laptop and on a phone, and click through both scenarios, the timeline cursor, the window finder's **Show** buttons and the sky explorer's A/B toggle.
- **Have a fallback.** Keep `docker compose up --build -d --wait` working locally. It serves the same archived data at `localhost:3000`, with no hosting involved.

## Troubleshooting

| Symptom                                                               | Cause and fix                                                                                            |
| --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| "Cannot reach the LunarWindow API at http://localhost:8000" on Vercel | `NEXT_PUBLIC_API_BASE_URL` was not set at build time. Set it and redeploy.                               |
| Browser console shows a CORS error                                    | The page origin is missing from `LUNARWINDOW_CORS_ORIGINS` on Render. Add it, then wait for the restart. |
| `/api/reference/sites` returns 503                                    | The reference bundle failed verification in the image. Rebuild from a clean checkout of `main`.          |
| Render health check fails                                             | Confirm `PORT=8000` is set; the container listens on 8000.                                               |
