# errt

The official home of errt — tiny software for everyday annoyances.

This is a dependency-free static site made for GitHub Pages. The published files live in `dist/`.

## File structure

```text
dist/
├── .nojekyll       # Disables Jekyll processing on GitHub Pages
├── favicon.svg
├── index.html
├── og-image.png
├── og-image.svg
├── site-config.js  # Product and social URLs
└── styles.css
scripts/
└── build.mjs       # Lightweight validation
.github/workflows/
└── deploy-pages.yml
```

## Local development

No dependency installation or compilation is required.

```sh
pnpm dev
```

Open `http://localhost:4173`. Run the same validation used in CI with:

```sh
pnpm build
```

## Update links

All product, X, and GitHub URLs live in `dist/site-config.js`. Replace the empty strings in `SITE_LINKS`; no HTML editing is needed. Empty URLs are displayed as unavailable links.

## Deploy to GitHub Pages

1. Create a GitHub repository and push this project to its `main` branch.
2. Open the repository's **Settings → Pages**.
3. Under **Build and deployment**, select **GitHub Actions** as the source.
4. Push to `main`, or run **Deploy to GitHub Pages** manually from the Actions tab.

The workflow validates the site, uploads only `dist/`, and deploys it to GitHub Pages. Asset paths are relative, so both `https://user.github.io/` and `https://user.github.io/repository/` work without edits.

## Custom domain

1. Open **Settings → Pages → Custom domain** and enter the domain.
2. Configure the required DNS record with your DNS provider.
   - For a subdomain such as `www.example.com`, create a `CNAME` pointing to `<user-or-org>.github.io` without a repository path.
   - For an apex domain such as `example.com`, use the current `A`, `AAAA`, `ALIAS`, or `ANAME` values from GitHub's documentation.
3. After DNS is active, enable **Enforce HTTPS** in the Pages settings.
4. Update the Open Graph image URL in `dist/index.html` to the final absolute domain if a social crawler does not resolve the relative URL.

With a custom Actions workflow, GitHub stores the custom-domain setting itself; a committed `CNAME` file is not required.

- [GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [GitHub Pages custom domains](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site)
