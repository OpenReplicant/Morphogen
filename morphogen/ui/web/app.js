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
  comment: 'http://www.w3.org/2000/01/rdf-schema#comment',
  version: 'http://www.w3.org/2002/07/owl#versionInfo',
  ontology: 'http://www.w3.org/2002/07/owl#Ontology',
  license: 'http://purl.org/dc/terms/license',
  hasPart: 'http://purl.org/dc/terms/hasPart',
  fills: 'https://w3id.org/knowledge-kernel/ns#fills',
  contract: 'https://w3id.org/knowledge-kernel/ns#slotContract',
  cardinality: 'https://w3id.org/knowledge-kernel/ns#cardinality',
  emits: 'https://w3id.org/knowledge-kernel/ns#emits',
  consumes: 'https://w3id.org/knowledge-kernel/ns#consumes',
  mayConsume: 'https://w3id.org/knowledge-kernel/ns#mayConsume',
};

// How the overview lays the slots out. A distribution's slots carry their phase in the record (its contract reads
// "<phase> phase"); the kernel's are grouped by where they sit around the commit. A slot in neither list still shows,
// under "Other".
const PHASES = [
  ['design', 'Design', 'A system is described, in an interview or from its files, and becomes a map.'],
  ['monitor', 'Monitor', 'What runs is observed.'],
  ['analyse', 'Analyse', 'What is wrong, or surprising, is found.'],
  ['plan', 'Plan', 'A change is proposed, with a prediction and a risk.'],
  ['execute', 'Execute', 'What a person approved is carried out.'],
  ['verify', 'Verify', 'The prediction is checked against what happened.'],
];
const KERNEL_GROUPS = [
  ['Writing', 'Every change passes these, before and at the commit.',
   ['intake-filter', 'validator', 'lane-policy', 'write-pipeline', 'record-store']],
  ['After the commit', 'They follow the change feed; what they find comes back as a proposal.',
   ['change-feed', 'belief-model', 'verifier', 'truth-maintenance', 'gap-finder']],
  ['Reading', 'How people and agents ask the record.', ['recall', 'agent-interface', 'context-assembler']],
  ['Upkeep', 'The vocabularies and the mappings between them, the record of itself, and measuring providers.',
   ['vocabulary-pack', 'mapping-set', 'self-encoder', 'evaluator', 'harness-adapter']],
];

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
    tab: 'overview', token: '', name: '', password: '', me: null, error: '', busy: false,
    queue: [], notes: {}, loop: [], plans: [], systems: [], system: '', graphInfo: '', rows: [], query: '', searched: false,
    detail: null, slot: null, overview: null, phases: PHASES, kernelGroups: KERNEL_GROUPS,

    async init() {
      try { this.token = sessionStorage.getItem('kk_token') || ''; } catch (e) { /* storage blocked */ }
      if (this.token) await this.signIn();
    },
    tabs() {
      return [{ id: 'overview', title: 'Overview' }, { id: 'review', title: 'Review' }, { id: 'loop', title: 'Loop' },
              { id: 'systems', title: 'Systems' },
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
      this.token = ''; this.me = null; this.overview = null; this.slot = null; this.queue = []; this.loop = []; this.plans = []; this.rows = []; this.detail = null; KK.token = '';
      if (!keepError) this.error = '';
      try { sessionStorage.removeItem('kk_token'); } catch (e) { /* storage blocked */ }
    },
    async run(fn) {
      this.error = ''; this.busy = true;
      try { await fn(); } catch (e) { this.error = e.message; } finally { this.busy = false; }
    },
    async open(tab) {
      this.tab = tab; this.detail = null; this.slot = null;
      if (tab === 'overview') await this.run(() => this.loadOverview());
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
      const kind = t => {                       // urn:kk:gap-kind:no-limit -> question · no limit
        const m = (t || '').match(/^urn:kk:([a-z-]+?)(?:-kind)?:(.+)$/);
        if (!m) return KK.short(t);
        const family = m[1] === 'gap' ? (m[2].startsWith('drift-') ? 'drift' : 'question') : m[1];
        return `${family} · ${m[2].replace(/^drift-/, '').replace(/-/g, ' ')}`;
      };
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

    // The overview: what the system is made of, read from the record (the self-encoder's claims about the blueprint,
    // each provider's manifest and the distribution, every one citing its file and line), what it has open, and where
    // each part can be swapped.
    async loadOverview() {
      const [slotRows, fills, ontologies, parts, runs, types, systems, me] = await Promise.all([
        KK.call('list_slots'),
        KK.call('query_claims', { predicate: NS.fills, limit: 1000 }),
        KK.call('query_claims', { predicate: NS.rdfType, object_entity: NS.ontology, limit: 200 }),
        KK.call('query_claims', { predicate: NS.hasPart, limit: 1000 }),
        KK.call('list_runs', { limit: 500 }),
        KK.call('query_claims', { predicate: NS.dctType, limit: 1000 }),
        KK.call('query_claims', { predicate: NS.rdfType, object_entity: NS.system, limit: 200 }),
        KK.call('whoami')]);
      this.me = me;
      const entity = iri => KK.call('get_entity', { iri });
      const about = (card, p) => card.claims.filter(c => c.predicate === p);
      const one = (card, p) => { const c = about(card, p)[0]; return c ? (c.object_entity || value({ value: c.object_value })) : ''; };
      const lastRun = {};
      for (const r of runs) {
        const name = KK.short(r.module || '').replace(/-v\d+$/, '');
        if (name && !(name in lastRun)) lastRun[name] = r;
      }
      const providerIris = [...new Set(fills.map(c => c.subject))];
      const [slotCards, providerCards, ontologyCards] = await Promise.all([
        Promise.all(slotRows.map(s => entity(s.iri))), Promise.all(providerIris.map(entity)),
        Promise.all(ontologies.map(c => entity(c.subject)))]);
      const providers = Object.fromEntries(providerCards.map(card => {
        const name = KK.short(card.iri);
        return [card.iri, { iri: card.iri, name, label: one(card, NS.label) || name, version: one(card, NS.version),
                            license: KK.short(one(card, NS.license)), slots: about(card, NS.fills).map(c => c.object_entity),
                            fills: Object.fromEntries(about(card, NS.fills).map(c => [c.object_entity, c])),
                            emits: about(card, NS.emits).map(c => c.object_entity),
                            consumes: about(card, NS.consumes).map(c => c.object_entity),
                            mayConsume: about(card, NS.mayConsume).map(c => c.object_entity), lastRun: lastRun[name] || null }];
      }));
      const distribution = {};
      for (const c of parts) if (c.subject.startsWith('urn:kk:distribution:')) (distribution[c.object_entity] ||= []).push(c.subject);
      const slots = slotCards.map(card => {
        const note = about(card, NS.comment)[0];
        const text = note ? value({ value: note.object_value }) : '';
        const m = text.match(/^Default provider: (.+) \(status ([^)]*)\)\.$/);
        const contract = one(card, NS.contract);
        const phase = (contract.match(/^(\w+) phase$/) || [])[1] || '';
        const defaults = m ? m[1].split(' + ').map(s => s.trim()) : [];
        const filling = Object.values(providers).filter(p => p.slots.includes(card.iri))
          .sort((a, b) => (defaults.includes(b.name) - defaults.includes(a.name)) || a.name.localeCompare(b.name));
        return { iri: card.iri, id: one(card, NS.label) || KK.short(card.iri), contract: phase ? '' : contract, phase,
                 cardinality: one(card, NS.cardinality) || 'one', note: text, noteId: note ? note.id : null,
                 status: m ? m[2] : (text.startsWith('Unfilled') ? 'unfilled' : ''), unfilled: text.startsWith('Unfilled'),
                 why: text.replace(/^Unfilled: no default provider\. ?/, ''), defaults, providers: filling,
                 kernel: KK.short(one(card, 'http://purl.org/dc/terms/isPartOf')) === 'kernel',
                 usedBy: (distribution[card.iri] || []).map(KK.short) };
      });
      const byId = Object.fromEntries(slots.map(s => [s.id, s]));
      const grouped = new Set();
      const take = ids => ids.map(id => byId[id]).filter(Boolean).map(s => { grouped.add(s.id); return s; });
      const phases = PHASES.map(([id, title, text]) => ({ id, title, text, slots: take(slots.filter(s => s.phase === id).map(s => s.id)) }));
      const kernel = KERNEL_GROUPS.map(([title, text, ids]) => ({ title, text, slots: take(ids) }));
      const other = slots.filter(s => !grouped.has(s.id));
      const gapKinds = types.filter(c => (c.object_entity || '').startsWith('urn:kk:gap-kind:')).map(c => KK.short(c.object_entity));
      this.overview = {
        slots, phases, kernel, other, providers: Object.values(providers),
        filled: slots.filter(s => !s.unfilled).length,
        swappable: slots.filter(s => this.alternatives(s)).length,
        questions: gapKinds.filter(k => !k.startsWith('drift')).length, drift: gapKinds.filter(k => k.startsWith('drift')).length,
        systems: systems.length, waiting: me.awaiting_review,
        vocabularies: ontologyCards.map(card => ({ iri: card.iri, label: one(card, NS.label) || KK.short(card.iri),
                                                   version: one(card, NS.version) }))
          .sort((a, b) => a.label.localeCompare(b.label)),
      };
    },
    // One slot in the side panel: its contract, who fills it, which is the default and where that is written (the
    // file and line the self-encoder's claim cites), and how a provider is swapped.
    async openSlot(s) {
      this.detail = null;
      this.slot = { ...s, where: '' };
      if (!s.noteId) return;
      await this.run(async () => {
        const ex = await KK.call('explain', { claim_id: s.noteId });
        const ref = (ex.references || [])[0];
        if (ref && this.slot && this.slot.iri === s.iri) {
          const line = ((ref.span || {}).value || '').replace(/^line=/, '');
          this.slot.where = String(ref.source_uri || '').replace(/^file:/, '') + (line ? ` line ${line}` : '');
        }
      });
    },
    alternatives: s => s.providers.filter(p => !s.defaults.includes(p.name)).length,
    ago(t) {
      if (!t) return '';
      const s = (Date.now() - new Date(t).getTime()) / 1000;
      if (s < 90) return 'just now';
      if (s < 5400) return `${Math.round(s / 60)} min ago`;
      if (s < 129600) return `${Math.round(s / 3600)} h ago`;
      return `${Math.round(s / 86400)} days ago`;
    },

    async find() {
      await this.run(async () => { this.rows = await KK.call('search', { text: this.query, limit: 50 }); this.searched = true; });
    },
    async explain(id) {
      this.slot = null;
      await this.run(async () => { this.detail = { id, body: await KK.call('explain', { claim_id: id }) }; });
    },
    // A claim read as a sentence, with where it came from.
    sentence(c) { return c ? `${KK.short(c.subject)} · ${KK.short(c.predicate)} · ${this.objectOf(c)}` : ''; },
    refText(r) {
      const span = r.span && r.span.value ? ` (${r.span.value})` : '';
      return String(r.source_uri || r.artifact_id || '') + span + (r.quote ? ` "${r.quote}"` : '');
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
