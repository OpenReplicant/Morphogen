"""Mutants the agent-interface slot's case set (kernel/contract/slots/agent-interface) must kill (kernel/contract/mutants.py)."""
S = "kernel_mcp/server.py"
MUTANTS = [
    ("claims answered without belief", S, [('"attributed_to, status, belief, valid_from, valid_to, recorded_at, change_set")',
                                            '"attributed_to, status, valid_from, valid_to, recorded_at, change_set")')]),
    ("a switching login is served", S, [("                elif (await (await conn.execute(SWITCHING_LOGIN)).fetchone())[0]:",
                                         "                elif False:")]),
    ("submissions attributed to the caller whoever they name", S, [
        ('    return await query(ctx, "select api.submit_change_set(%s)", (Jsonb(change_set),))',
         '    me = await query(ctx, "select kernel.my_agent()")\n'
         '    return await query(ctx, "select api.submit_change_set(%s)", (Jsonb({**change_set, "attributed_to": me}),))')]),
    ("get_change_set renamed", S, [("async def get_change_set(ctx: Context, change_set_id: str) -> dict:",
                                    "async def change_set(ctx: Context, change_set_id: str) -> dict:")]),
    ("mappings not followed", S, [("ways = {k: mappings.reach(found, params[k]) if params[k] else None",
                                   "ways = {k: {params[k]: []} if params[k] else None")], "own"),
    ("an answer through a mapping cites nothing", S, [('            c["via"] = [mapped.get(i, {"id": i}) for i in dict.fromkeys(via)]', "            pass")], "own"),
    ("a mapping cited without its belief", S, [('            c["via"] = [mapped.get(i, {"id": i}) for i in dict.fromkeys(via)]',
                                                 '            c["via"] = [{"id": i} for i in dict.fromkeys(via)]')], "own"),
]
