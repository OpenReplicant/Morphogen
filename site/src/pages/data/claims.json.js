// data/claims.json: the same records the pages are built from, for other tools.
import { claimsJson } from "../../lib/data.mjs";
import { getSite } from "../../lib/site.mjs";

export async function GET() {
  return new Response(JSON.stringify(claimsJson(await getSite()), null, 1));
}
