// Morphogen's UI (T21; rebuild 4 modules/ui/web/app.js, D-44). An MCP client: every call carries the signed-in
// person's own token, so the store decides what they see and what they may approve, never this page.
let cy = null;  // the Cytoscape instance stays outside Alpine's reactive state

const NS = {
  rdfType: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
  label: 'http://www.w3.org/2000/01/rdf-schema#label',
  dctType: 'http://purl.org/dc/terms/type',
  plan: 'http://purl.org/net/p-plan#Plan',
  stepOf: 'http://purl.org/net/p-plan#isStepOfPlan',
  foi: 'http://www.w3.org/ns/sosa/hasFeatureOfInterest',
  result: 'http://www.w3.org/ns/sosa/hasSimpleResult',
  prop: 'http://www.w3.org/ns/sosa/observedProperty',
  max: 'https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue',
  partOf: 'http://purl.org/dc/terms/isPartOf',
  substitutedBy: 'https://w3id.org/knowledge-kernel/tosca#substitutedBy',
  body: 'http://www.w3.org/ns/oa#bodyValue',
  target: 'http://www.w3.org/ns/oa#hasTarget',
  system: 'https://w3id.org/knowledge-kernel/tosca#ServiceTemplate',
};

const KK = {
  token: '',

  // One MCP tool call (streamable HTTP, stateless, JSON response) with the person's own token.
  async call(name, args = {}) {
    const r = await fetch('/mcp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream',
                 ...(KK.token ? { Authorization: 'Bearer ' + KK.token } : {}) },
      body: JSON.stringify({ jsonrpc: '2.0', id: Date.now(), method: 'tools/call', params: { name, arguments: args } }),
    });
    if (!r.ok) throw new Error(`${r.status} ${(await r.text()) || r.statusText}`);
    const msg = await r.json();
    if (msg.error) throw new Error(msg.error.message);
    const res = msg.result, text = res.content && res.content[0] ? res.content[0].text : '';
    if (res.isError) throw new Error(text);
    if (res.structuredContent) return 'result' in res.structuredContent ? res.structuredContent.result : res.structuredContent;
    return text ? JSON.parse(text) : null;
  },

  short(iri) {
    if (!iri) return '';
    const m = String(iri).match(/[#/:]([^#/:]+)\/?$/);
    return m ? m[1] : iri;
  },
};

const value = o => (o && o.value && o.value['@value'] !== undefined ? o.value['@value'] : o && o.entity);

// What a change set proposes, read from its ops: a plan (label, risk, its step: action, target and the value it
// sets or the candidate it substitutes; its prediction) when it holds one, and the claims every op cites.
function readPlan(ops) {
  const of = (s, p) => ops.find(o => o.op === 'add_claim' && o.subject === s && o.predicate === p);
  const planOp = ops.find(o => o.op === 'add_claim' && o.predicate === NS.rdfType && value(o.object) === NS.plan);
  const cited = [...new Set(ops.flatMap(o => o.derived_from || []))];
  if (!planOp) return { plan: null, cited };
  const iri = planOp.subject;
  const stepOp = ops.find(o => o.predicate === NS.stepOf && value(o.object) === iri);
  const step = stepOp ? stepOp.subject : null;
  const prediction = ops.find(o => o.predicate === NS.max && o.qualifiers && o.qualifiers[NS.partOf] === iri);
  const risk = value((of(iri, NS.dctType) || {}).object) || '';
  return {
    cited,
    plan: {
      iri, label: value((of(iri, NS.label) || {}).object) || iri, risk: KK.short(risk),
      action: step ? KK.short(value((of(step, NS.dctType) || {}).object)) : '',
      target: step ? value((of(step, NS.foi) || {}).object) : '',
      to: step ? value((of(step, NS.result) || {}).object) : null,
      candidate: step ? value((of(step, NS.substitutedBy) || {}).object) : null,
      prediction: prediction ? { of: prediction.subject, property: KK.short(prediction.qualifiers[NS.prop]),
                                 limit: value(prediction.object) } : null,
    },
  };
}

function shell() {
  return {
    tab: 'review', token: '', name: '', password: '', me: null, error: '', busy: false,
    queue: [], notes: {}, loop: [], plans: [], systems: [], system: '', graphInfo: '', rows: [], query: '', searched: false,
    detail: null,

    async init() {
      try { this.token = sessionStorage.getItem('kk_token') || ''; } catch (e) { /* storage blocked */ }
      if (this.token) await this.signIn();
    },
    tabs() {
      return [{ id: 'review', title: 'Review' }, { id: 'loop', title: 'Loop' }, { id: 'systems', title: 'Systems' },
              { id: 'search', title: 'Search' }, { id: 'me', title: 'Me' }];
    },
    async signIn() {
      KK.token = this.token;
      try { sessionStorage.setItem('kk_token', this.token); } catch (e) { /* storage blocked */ }
      await this.run(async () => { this.me = await KK.call('whoami'); });
      if (this.me) await this.open(this.tab); else this.signOut(true);
    },
    async login() {
      await this.run(async () => {
        const r = await fetch('/ui/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                             body: JSON.stringify({ name: this.name, password: this.password }) });
        const body = await r.json();
        if (!r.ok) throw new Error(body.error || r.statusText);
        this.token = body.token;
      });
      this.password = '';
      if (this.token) await this.signIn();
    },
    signOut(keepError = false) {
      this.token = ''; this.me = null; this.queue = []; this.loop = []; this.plans = []; this.rows = []; this.detail = null; KK.token = '';
      if (!keepError) this.error = '';
      try { sessionStorage.removeItem('kk_token'); } catch (e) { /* storage blocked */ }
    },
    async run(fn) {
      this.error = ''; this.busy = true;
      try { await fn(); } catch (e) { this.error = e.message; } finally { this.busy = false; }
    },
    async open(tab) {
      this.tab = tab; this.detail = null;
      if (tab === 'review') await this.run(() => this.loadQueue());
      if (tab === 'loop') await this.run(() => this.loadLoop());
      if (tab === 'systems') await this.run(() => this.loadSystems());
      if (tab === 'me') await this.run(async () => { this.me = await KK.call('whoami'); });
    },

    // The review lane: each change set waiting for a person, read as a plan with the claims it cites.
    async loadQueue() {
      const rows = await KK.call('review_queue');
      this.queue = await Promise.all(rows.map(async r => {
        const { plan, cited } = readPlan(r.ops || []);
        const claims = await Promise.all(cited.slice(0, 20).map(async id => {
          try { return (await KK.call('explain', { claim_id: id })).claim; } catch (e) { return { id, unreadable: true }; }
        }));
        return { ...r, plan, cited: claims, more: Math.max(0, cited.length - 20) };
      }));
    },
    async decide(id, approve) {
      if (!approve && !(this.notes[id] || '').trim()) { this.error = 'Say why in the note before refusing.'; return; }
      await this.run(async () => {
        await KK.call('review', { change_set_id: id, approve, note: this.notes[id] || null });
        await this.loadQueue();
      });
    },

    // The loop: what the analyser, planner and verifier recorded, newest first: each annotation's kind, target
    // and sentence (anomalies, build requests, gaps, verdicts); and each plan from proposal to verdict.
    async loadLoop() {
      const [bodies, types, targets, plans, labels, steps, sets] = await Promise.all([
        KK.call('query_claims', { predicate: NS.body, limit: 500 }),
        KK.call('query_claims', { predicate: NS.dctType, limit: 1000 }),
        KK.call('query_claims', { predicate: NS.target, limit: 1000 }),
        KK.call('query_claims', { predicate: NS.rdfType, object_entity: NS.plan, limit: 200 }),
        KK.call('query_claims', { predicate: NS.label, limit: 1000 }),
        KK.call('query_claims', { predicate: NS.stepOf, limit: 1000 }),
        KK.call('list_change_sets', { limit: 500 })]);
      const typeOf = Object.fromEntries(types.map(c => [c.subject, c.object_entity]));
      const targetOf = Object.fromEntries(targets.map(c => [c.subject, c.object_entity]));
      const kind = t => (t || '').replace(/^urn:kk:/, '').replace(/:/g, ' · ');
      this.loop = bodies.map(c => ({ id: c.id, subject: c.subject, kind: kind(typeOf[c.subject]),
                                     target: targetOf[c.subject] || '', text: value(c.object_value ? { value: c.object_value } : null),
                                     belief: c.belief, at: c.valid_from || c.recorded_at || '' }))
        .sort((a, b) => String(b.at).localeCompare(String(a.at)));
      this.plans = await this.readPlans(plans, labels, steps, sets, typeOf);
    },

    // Each plan: who decided it (the change set that recorded it, reviewed by a person), whether a step was
    // carried out (a run naming the step: the actuator records what it did as runs, never claims), and the
    // verifier's verdict on its prediction (an annotation targeting the plan). The record links them; the page
    // only puts them side by side.
    async readPlans(plans, labels, steps, sets, typeOf) {
      const labelOf = Object.fromEntries(labels.map(c => [c.subject, value({ value: c.object_value })]));
      const setOf = Object.fromEntries(sets.map(s => [s.id, s]));
      const verdicts = this.loop.filter(e => /^verdict/.test(e.kind));
      return Promise.all(plans.map(async p => {
        const cs = setOf[p.change_set] || {};
        const mine = steps.filter(c => c.object_entity === p.subject).map(c => c.subject);
        const runs = (await Promise.all(mine.map(s => KK.call('list_runs', { plan_step: s, limit: 5 })))).flat()
          .filter(r => r.status !== 'running')
          .sort((a, b) => String(b.ended_at || b.started_at).localeCompare(String(a.ended_at || a.started_at)));
        const v = verdicts.find(e => e.target === p.subject);
        return { iri: p.subject, label: labelOf[p.subject] || p.subject, risk: KK.short(typeOf[p.subject] || ''),
                 status: cs.status || '', decidedBy: cs.decided_by || '', decidedAt: cs.decided_at || '', note: cs.review_note || '',
                 run: runs.length ? runs[0] : null,
                 verdict: v ? { id: v.id, kind: KK.short(typeOf[v.subject]), text: v.text, belief: v.belief } : null,
                 at: p.recorded_at || '' };
      })).then(rows => rows.sort((a, b) => String(b.at).localeCompare(String(a.at))));
    },

    // The managed systems (encoder-compose's maps): each a graph of its services and who connects to whom.
    async loadSystems() {
      this.systems = (await KK.call('query_claims', { predicate: NS.rdfType, object_entity: NS.system, limit: 200 }))
        .map(c => c.subject);
      if (!this.system && this.systems.length) this.system = this.systems[0];
      if (this.system) await this.drawSystem();
    },
    async drawSystem() {
      const g = await KK.call('graph', { root: this.system, depth: 2 });
      const css = getComputedStyle(document.documentElement), v = name => css.getPropertyValue(name).trim();
      if (cy) cy.destroy();
      cy = cytoscape({
        container: document.getElementById('cy'), elements: g, wheelSensitivity: 0.3,
        layout: { name: 'cose', padding: 20, animate: false },
        style: [
          { selector: 'node', style: { 'background-color': n => v('--k-' + n.data('kind')) || v('--k-entity'),
              label: 'data(label)', 'font-size': 10, color: v('--fg'), 'text-wrap': 'ellipsis', 'text-max-width': 140,
              width: 16, height: 16 } },
          { selector: 'edge', style: { 'curve-style': 'bezier', 'target-arrow-shape': 'triangle',
              'line-color': v('--edge'), 'target-arrow-color': v('--edge'),
              width: e => 0.5 + 3 * (e.data('belief') ?? 0), opacity: e => 0.3 + 0.7 * (e.data('belief') ?? 0),
              label: 'data(label)', 'font-size': 8, color: v('--muted'), 'text-rotation': 'autorotate' } },
          { selector: 'edge[belief < 0.5]', style: { 'line-style': 'dashed' } },
        ],
      });
      cy.on('tap', 'edge', ev => this.explain(ev.target.id()));
      const el = document.getElementById('cy');
      el.dataset.nodes = cy.nodes().length; el.dataset.edges = cy.edges().length;
      this.graphInfo = `${cy.nodes().length} entities, ${cy.edges().length} claims`;
    },

    async find() {
      await this.run(async () => { this.rows = await KK.call('search', { text: this.query, limit: 50 }); this.searched = true; });
    },
    async explain(id) {
      await this.run(async () => { this.detail = { id, body: await KK.call('explain', { claim_id: id }) }; });
    },

    short: iri => KK.short(iri),
    belief: b => (b === null || b === undefined ? '—' : Number(b).toFixed(2)),
    objectOf(c) {
      if (!c) return '';
      if (c.object_entity) return KK.short(c.object_entity);
      const v = c.object_value && c.object_value['@value'];
      return v === undefined ? JSON.stringify(c.object_value) : String(v);
    },
    opText(op) {
      if (op.op === 'add_claim') return `${KK.short(op.subject)} ${KK.short(op.predicate)} ${KK.short(String(value(op.object) ?? ''))}`;
      return op.claim ? `${op.claim} → ${op.status || ''} ${op.reason || ''}` : JSON.stringify(op);
    },
  };
}
