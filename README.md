# errt

The official home of errt — tiny software for everyday annoyances.

## Local development

No dependency installation or build step is required.

```sh
pnpm dev
```

Then open `http://localhost:4173`.

Run the lightweight content/file check with:

```sh
pnpm build
```

## Update links

All product, X, and GitHub URLs live in `dist/site-config.js`. Replace the empty strings in `SITE_LINKS`; no HTML editing is needed.

## Deploy

### Cloudflare Pages

- Connect this repository in Cloudflare Pages.
- Framework preset: `None`
- Build command: leave empty (or use `pnpm build`)
- Build output directory: `dist`

### Vercel

- Import this repository in Vercel.
- Framework preset: `Other`
- Build command: leave empty (or use `pnpm build`)
- Output directory: `dist`

The site is plain static HTML/CSS with one tiny configuration script, so no runtime or environment variables are needed.
