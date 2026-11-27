// The file-based pages: every Markdown file under site/content (or SITE_CONTENT) becomes a page with the shared
// layout (src/pages/[...slug].astro). Front matter is checked here; a page that breaks it stops the build.
import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

const day = z.union([z.string(), z.date()]).transform((d) => (typeof d === "string" ? d : d.toISOString().slice(0, 10)));

const pages = defineCollection({
  loader: glob({ pattern: "**/*.md", base: process.env.SITE_CONTENT || "./content" }),
  schema: z.object({
    title: z.string(),
    description: z.string().optional(),
    // page: a page of its own; note and announcement: also listed, newest first, on notes.html
    kind: z.enum(["page", "note", "announcement"]).default("note"),
    date: day.optional(),
    // entities this page is about, e.g. resource:inkling-2-mini-q4-k, trial:E-04a, claim:<name>, role:<name>,
    // option:<name>, paper:arXiv:2610.00346; each entity's page links back here
    refs: z.array(z.string()).default([]),
    // a number puts the page in the header's navigation, in that order
    nav: z.number().optional(),
    // generated sections to add after the text: statuses, steering, files
    blocks: z.array(z.enum(["statuses", "steering", "files"])).default([]),
    draft: z.boolean().default(false),
  }),
});

export const collections = { pages };
