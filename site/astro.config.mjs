// The research site (site/README.md), built from the config file in MORPHOGEN_SITE_CONFIG (src/lib/config.mjs).
// Static output only; every page is a file such as claims/<name>.html. Links are relative, so the site works under
// any path, unless MORPHOGEN_SITE_BASE (`morphogen site build --base /research`) makes them start with that path.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "astro/config";
import { loadConfig, themeFiles } from "./src/lib/config.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
process.env.SITE_DIR ||= HERE; // read by src/lib/config.mjs
const CFG = loadConfig();

// The config's theme (themeFiles, in src/lib/config.mjs): written into the output after a build as assets/user/;
// served from the config's own files by the dev server.
const TYPES = { ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg" };

function userTheme() {
  const files = themeFiles(CFG.theme);
  return {
    name: "user-theme",
    hooks: {
      "astro:config:setup": ({ updateConfig }) => {
        updateConfig({ vite: { plugins: [{ name: "user-theme-dev", configureServer(server) {
          server.middlewares.use((req, res, next) => {
            const m = /\/assets\/user\/([^/?#]+)/.exec(req.url || "");
            if (!m || !files[m[1]]) return next();
            res.setHeader("Content-Type", TYPES[path.extname(m[1])] || "application/octet-stream");
            res.end(fs.readFileSync(files[m[1]]));
          });
        } }] } });
      },
      "astro:build:done": ({ dir }) => {
        const out = path.join(fileURLToPath(dir), "assets", "user");
        if (!Object.keys(files).length) return;
        fs.mkdirSync(out, { recursive: true });
        for (const [name, from] of Object.entries(files)) fs.copyFileSync(from, path.join(out, name));
      },
    },
  };
}

// Alpine's CSP build (no `new Function`, so the content security policy needs no 'unsafe-eval'), served from the
// site itself: copied from the pinned package into public/assets/vendor before every build and dev start.
function alpineCsp() {
  return {
    name: "alpine-csp",
    hooks: {
      "astro:config:setup": () => {
        const pkg = path.join(HERE, "node_modules", "@alpinejs", "csp");
        const out = path.join(HERE, "public", "assets", "vendor");
        fs.mkdirSync(out, { recursive: true });
        const { version, license } = JSON.parse(fs.readFileSync(path.join(pkg, "package.json"), "utf8"));
        const code = fs.readFileSync(path.join(pkg, "dist", "cdn.min.js"), "utf8");
        fs.writeFileSync(path.join(out, "alpine-csp.min.js"),
          `/*! @alpinejs/csp ${version} | ${license} licence | https://github.com/alpinejs/alpine */\n${code}`);
      },
    },
  };
}

export default defineConfig({
  output: "static",
  outDir: process.env.MORPHOGEN_SITE_OUT ? path.resolve(process.env.MORPHOGEN_SITE_OUT) : "./_build",
  base: CFG.base || undefined,
  build: { format: "file" },
  compressHTML: true,
  devToolbar: { enabled: false },
  integrations: [alpineCsp(), userTheme()],
});
