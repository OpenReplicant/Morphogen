// The research site (site/README.md). Static output only; every page is a file such as claims/<name>.html, and
// every link is relative, so the site works under https://<owner>.github.io/Morphogen/ or on its own domain.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "astro/config";

const HERE = path.dirname(fileURLToPath(import.meta.url));
process.env.SITE_DIR ||= HERE; // read by src/lib/data.mjs

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
  outDir: process.env.SITE_OUT || "./_build",
  build: { format: "file" },
  compressHTML: true,
  devToolbar: { enabled: false },
  integrations: [alpineCsp()],
});
