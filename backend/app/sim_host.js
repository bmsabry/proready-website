/* Server-side host for a browser simulator engine.
 *
 * Runs inside V8 embedded in the API process (app/sim_runtime.py). The
 * engine itself — the model, its data, its coefficients — is NOT here: it is
 * loaded from a protected blob at runtime and never leaves the server. This
 * file is the generic plumbing around it: one engine instance per learner
 * session, a whitelist of what a browser may set, and a snapshot of what a
 * browser may read.
 *
 * Contract with the engine bundle: after it is evaluated, `DLN.Engine` is a
 * constructor (machineKey, shaft, limitSet) whose instances expose the
 * properties and methods listed in SNAPSHOT / SETTABLE below; `DLN_DATA` may
 * carry a `sensitivity` table used by respondingBands(); and `DLN.interp`
 * is a breakpoint interpolator. Nothing else is assumed.
 */
'use strict';

var __S = {};   /* session id -> engine */

/* Properties a browser may set directly, and the sub-objects it may write
 * into. Anything else is refused. Values are bounded in __set(). */
var SETTABLE = {
  tnh: 'num', ttrf1: 'num', ttrf1cmd: 'num', ftg: 'num', mwiDesign: 'num',
  breaker: 'bool', limitSet: 'str', path: 'str', loadMW: 'numnull',
  loadSetpoint: 'numnull', rampMWperMin: 'num', ctim: 'num', sh: 'num',
  tune: 'obj', faults: 'obj', prot: 'obj', instr: 'obj'
};
var SUB_SETTABLE = { prot: { purgeFault: true }, instr: { fieldVariation: true },
                     faults: { gcvStuck: true, purge: true, d5PurgeT: true, pm2Broken: true },
                     tune: true };
var STRINGS = { limitSet: ['tuning', 'final'], path: ['primary', 'backup'] };
var NUM_BOUNDS = { tnh: [0, 120], ttrf1: [0, 3000], ttrf1cmd: [0, 3000], ftg: [-50, 700],
                   mwiDesign: [1, 200], loadMW: [0, 400], loadSetpoint: [0, 400],
                   rampMWperMin: [0.5, 100], ctim: [-40, 130], sh: [0, 0.05] };

function __bounded(key, v) {
  var b = NUM_BOUNDS[key];
  if (!b || typeof v !== 'number' || !isFinite(v)) return v;
  return Math.max(b[0], Math.min(b[1], v));
}

function __new(id, key, shaft, limitSet) {
  if (typeof DLN === 'undefined' || !DLN.Engine) throw new Error('engine bundle not loaded');
  __S[id] = new DLN.Engine(String(key), String(shaft || 'multi'), String(limitSet || 'tuning'));
  return JSON.stringify({ deck: __S[id].deck, state: __stateObj(id, false) });
}

function __drop(id) { delete __S[id]; return Object.keys(__S).length; }
function __count() { return Object.keys(__S).length; }

/* set a whitelisted property, possibly nested: path is a JSON array */
function __set(id, pathJson, valueJson) {
  var e = __S[id]; if (!e) throw new Error('no session');
  var path = JSON.parse(pathJson), value = JSON.parse(valueJson);
  var head = path[0];
  var kind = SETTABLE[head];
  if (!kind) throw new Error('not settable: ' + head);
  if (path.length === 1) {
    if (kind === 'num') { if (typeof value !== 'number') throw new Error('number expected'); e[head] = __bounded(head, value); }
    else if (kind === 'numnull') { if (value !== null && typeof value !== 'number') throw new Error('number or null expected'); e[head] = value === null ? null : __bounded(head, value); }
    else if (kind === 'bool') e[head] = !!value;
    else if (kind === 'str') { if (STRINGS[head].indexOf(value) < 0) throw new Error('bad value for ' + head); e[head] = value; }
    else if (kind === 'obj') {
      if (head !== 'tune') throw new Error('cannot replace ' + head);
      if (value === null || typeof value !== 'object') throw new Error('object expected');
      e.tune = {};   /* the only whole-object write the UI makes: zero all biases */
    }
    return __stateJson(id, false);
  }
  if (kind !== 'obj') throw new Error('not an object: ' + head);
  var allowed = SUB_SETTABLE[head];
  if (allowed !== true && !allowed[path[1]]) throw new Error('not settable: ' + head + '.' + path[1]);
  if (path.length > 3) throw new Error('path too deep');
  for (var i = 1; i < path.length; i++) {
    if (!/^[A-Za-z0-9_.\-]{1,32}$/.test(String(path[i]))) throw new Error('bad path');
  }
  if (typeof value === 'string' && value.length > 64) throw new Error('string too long');
  if (value !== null && typeof value === 'object') {
    /* the one nested object write the UI makes: tune[mode] = tune[mode] || {} */
    if (head !== 'tune' || path.length !== 2 || Array.isArray(value)) throw new Error('primitive expected');
    var cur = e.tune[path[1]] || {};
    Object.keys(value).forEach(function (c) {
      if (/^[A-Z0-9]{2,4}$/.test(c) && typeof value[c] === 'number' && isFinite(value[c])) cur[c] = Math.max(-20, Math.min(20, value[c]));
    });
    e.tune[path[1]] = cur;
    return __stateJson(id, false);
  }
  if (typeof value === 'number' && !isFinite(value)) throw new Error('bad number');
  var o = e[head];
  for (var j = 1; j < path.length - 1; j++) {
    if (o[path[j]] === null || typeof o[path[j]] !== 'object') o[path[j]] = {};
    o = o[path[j]];
  }
  var leaf = path[path.length - 1];
  if (head === 'tune' && typeof value === 'number') value = Math.max(-20, Math.min(20, value));
  o[leaf] = value;
  return __stateJson(id, false);
}

function __del(id, pathJson) {
  var e = __S[id]; if (!e) throw new Error('no session');
  var path = JSON.parse(pathJson);
  var head = path[0];
  if (SETTABLE[head] !== 'obj' || path.length < 2 || path.length > 3) throw new Error('cannot delete ' + path.join('.'));
  var allowed = SUB_SETTABLE[head];
  if (allowed !== true && !allowed[path[1]]) throw new Error('not deletable');
  var o = e[head];
  for (var j = 1; j < path.length - 1; j++) { if (!o[path[j]]) return __stateJson(id, false); o = o[path[j]]; }
  delete o[path[path.length - 1]];
  return __stateJson(id, false);
}

/* the few methods a browser may call */
function __call(id, fn, argsJson) {
  var e = __S[id]; if (!e) throw new Error('no session');
  var args = JSON.parse(argsJson);
  if (fn === 'setBlend') { e.setBlend(String(args[0]).slice(0, 64)); }
  else if (fn === 'resetTrip') { e.resetTrip(); }
  else if (fn === 'log') { e.log(String(args[0]).slice(0, 200)); }
  else throw new Error('not callable: ' + fn);
  return __stateJson(id, false);
}

/* first render: the browser build stepped 1e-4 s if it had no frame yet */
function __prime(id) {
  var e = __S[id]; if (!e) throw new Error('no session');
  if (!e.last) e.step(0.0001);
  return __stateJson(id, false);
}

/* advance n seconds in 1 s steps; return every frame plus the state after */
function __tick(id, n, wantMargin) {
  var e = __S[id]; if (!e) throw new Error('no session');
  var fr = [];
  n = Math.max(1, Math.min(60, n | 0));
  for (var i = 0; i < n; i++) { e.step(1.0); fr.push(e.last); }
  return JSON.stringify({ frames: fr, state: __stateObj(id, !!wantMargin) });
}

/* which bands respond to moving each circuit, at this mode and TTRF1 —
 * the sensitivity table stays on the server; only the answer travels */
function __responding(e) {
  var out = {};
  var sens = (typeof DLN_DATA !== 'undefined' && DLN_DATA.sensitivity && DLN_DATA.sensitivity.bands) || {};
  var modeKey = e.mode + ((e.mode === '6.2' && e.shaft === 'single') ? '_single' : '');
  var tbl = sens[modeKey] || {};
  ['D5', 'PM1', 'PM3', 'PM2'].forEach(function (circuit) {
    var r = {};
    Object.keys(tbl).forEach(function (band) {
      var s = tbl[band][circuit];
      if (s == null) return;
      var v = (typeof s === 'number') ? s : DLN.interp(s, e.ttrf1);
      if (Math.abs(v) >= 0.02) r[band] = v;
    });
    out[circuit] = r;
  });
  return out;
}

function __stateObj(id, wantMargin) {
  var e = __S[id];
  var P = e.prot || {};
  var st = {
    t: e.t, tnh: e.tnh, breaker: e.breaker, ttrf1: e.ttrf1, ttrf1cmd: e.ttrf1cmd,
    igv: e.igv, ctim: e.ctim, sh: e.sh, ftg: e.ftg, lhv: e.lhv, sg: e.sg,
    blend: e.blend, mwiDesign: e.mwiDesign, path: e.path, mode: e.mode,
    transfer: e.transfer, purgeEnabled: e.purgeEnabled, tune: e.tune,
    loadMW: e.loadMW, rampMWperMin: e.rampMWperMin, loadSetpoint: e.loadSetpoint,
    atBaseLoad: e.atBaseLoad, faults: e.faults, events: e.events, key: e.key,
    shaft: e.shaft, limitSet: e.limitSet, cond60: e.cond60 || null,
    prot: { severity: P.severity, findings: P.findings, lockouts: P.lockouts,
            runback: P.runback, loadLimit: P.loadLimit, tripped: P.tripped,
            tripCause: P.tripCause, d5Low: P.d5Low, d5LowLow: P.d5LowLow,
            purgeFault: P.purgeFault, tripAt: P.tripAt, tripSnapshot: P.tripSnapshot,
            over: P.over, gcvOver: P.gcvOver },
    instr: { fieldVariation: e.instr ? e.instr.fieldVariation : true },
    last: e.last || null,
    responding: __responding(e)
  };
  if (wantMargin) st.margin = e.marginReport();
  return st;
}

function __stateJson(id, wantMargin) { return JSON.stringify(__stateObj(id, wantMargin)); }

/* display constants the thin client needs; sent once per connection */
function __consts() {
  var lim = (typeof DLN_DATA !== 'undefined' && DLN_DATA.limits) || {};
  return JSON.stringify({
    BANDS: DLN.BANDS, BAND_TONE: DLN.BAND_TONE, CIRCUITS: DLN.CIRCUITS,
    EVEN_OUTER: DLN.EVEN_OUTER, FUEL_BLENDS: DLN.FUEL_BLENDS,
    MAX_OVER_MEAN_CAN: DLN.MAX_OVER_MEAN_CAN,
    TUNING_LIMIT: DLN.TUNING_LIMIT, FINAL_TUNE: DLN.FINAL_TUNE,
    noxTargetCurve: lim.NOx_vs_specific_humidity_target_ppm15O2 || []
  });
}
