// data/search.json: the same records the pages are built from, for other tools.
import { searchJson } from "../../lib/data.mjs";
import { getSite } from "../../lib/site.mjs";

export async function GET() {
  return new Response(JSON.stringify(searchJson(await getSite()), null, 1));
}
