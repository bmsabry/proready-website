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

var __S = Object.create(null);   /* session id -> engine */

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

function __own(obj, key) { return !!obj && Object.prototype.hasOwnProperty.call(obj, key); }
function __record(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function __safeKey(key) {
  return typeof key === 'string' && /^[A-Za-z0-9_.\-]{1,32}$/.test(key) &&
    key !== '__proto__' && key !== 'prototype' && key !== 'constructor';
}
function __path(json, min) {
  var path = JSON.parse(json);
  if (!Array.isArray(path) || path.length < min || path.length > 3 || !path.every(__safeKey)) {
    throw new Error('bad path');
  }
  return path;
}
function __mode(e, mode) {
  if (!__safeKey(mode) || !e.deck || !__own(e.deck.modes, mode)) throw new Error('unknown tuning mode');
  return e.deck.modes[mode];
}
function __tuneWindow(e, mode, circuit) {
  var md = __mode(e, mode);
  if (!__safeKey(circuit) || !__own(md.schedules, circuit) || !__own(md.window, circuit)) {
    throw new Error('circuit not tunable in mode');
  }
  var window = md.window[circuit];
  if (typeof window !== 'number' || !isFinite(window) || window < 0) throw new Error('bad tuning window');
  return window;
}
function __writeTune(e, mode, circuit, value) {
  var window = __tuneWindow(e, mode, circuit);
  if (typeof value !== 'number' || !isFinite(value)) throw new Error('finite tuning bias expected');
  if (typeof e.setTuneBias === 'function') {
    // The engine accounts for an applied learner map before clamping a trim.
    e.setTuneBias(mode, circuit, value);
  } else {
    if (!__own(e.tune, mode)) e.tune[mode] = {};
    e.tune[mode][circuit] = Math.max(-window, Math.min(window, value));
  }
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
  var path = __path(pathJson, 1), value = JSON.parse(valueJson);
  var head = path[0];
  if (!__own(SETTABLE, head)) throw new Error('not settable: ' + head);
  var kind = SETTABLE[head];
  if (head === 'tune') {
    if (path.length === 1) {
      if (!__record(value) || Object.keys(value).length) throw new Error('empty tuning object expected');
      e.tune = {};
    } else if (path.length === 2) {
      __mode(e, path[1]);
      if (!__record(value)) throw new Error('tuning object expected');
      // Validate the complete update before writing any member.
      Object.keys(value).forEach(function (c) {
        __tuneWindow(e, path[1], c);
        if (typeof value[c] !== 'number' || !isFinite(value[c])) throw new Error('finite tuning bias expected');
      });
      if (!__own(e.tune, path[1])) e.tune[path[1]] = {};
      Object.keys(value).forEach(function (c) { __writeTune(e, path[1], c, value[c]); });
    } else {
      __writeTune(e, path[1], path[2], value);
    }
    return __stateJson(id, false);
  }
  if (path.length === 1) {
    if (kind === 'num') { if (typeof value !== 'number' || !isFinite(value)) throw new Error('finite number expected'); e[head] = __bounded(head, value); }
    else if (kind === 'numnull') { if (value !== null && (typeof value !== 'number' || !isFinite(value))) throw new Error('finite number or null expected'); e[head] = value === null ? null : __bounded(head, value); }
    else if (kind === 'bool') { if (typeof value !== 'boolean') throw new Error('boolean expected'); e[head] = value; }
    else if (kind === 'str') { if (STRINGS[head].indexOf(value) < 0) throw new Error('bad value for ' + head); e[head] = value; }
    else if (kind === 'obj') throw new Error('cannot replace ' + head);
    return __stateJson(id, false);
  }
  if (kind !== 'obj') throw new Error('not an object: ' + head);
  var allowed = SUB_SETTABLE[head];
  if (!__own(allowed, path[1])) throw new Error('not settable: ' + head + '.' + path[1]);
  var keyedFault = head === 'faults' && (path[1] === 'gcvStuck' || path[1] === 'purge');
  if (keyedFault) {
    if (path.length !== 3 || ['D5', 'PM1', 'PM3', 'PM2'].indexOf(path[2]) < 0) throw new Error('bad fault circuit');
    if (path[1] === 'gcvStuck') {
      if (typeof value !== 'number' || !isFinite(value)) throw new Error('finite fault offset expected');
      value = Math.max(-100, Math.min(100, value));
    } else if (['loss_of_purge', 'loss_of_blocking'].indexOf(value) < 0) throw new Error('bad purge fault');
  } else {
    if (path.length !== 2) throw new Error('path too deep');
    if (head === 'prot' && value !== null) throw new Error('purge timer may only be cleared');
    if ((head === 'instr' || path[1] === 'pm2Broken') && typeof value !== 'boolean') throw new Error('boolean expected');
    if (path[1] === 'd5PurgeT' && value !== null) {
      if (typeof value !== 'number' || !isFinite(value)) throw new Error('finite temperature or null expected');
      value = Math.max(-50, Math.min(1000, value));
    }
  }
  var o = e[head];
  for (var j = 1; j < path.length - 1; j++) {
    if (!__own(o, path[j]) || !__record(o[path[j]])) o[path[j]] = {};
    o = o[path[j]];
  }
  var leaf = path[path.length - 1];
  o[leaf] = value;
  return __stateJson(id, false);
}

function __del(id, pathJson) {
  var e = __S[id]; if (!e) throw new Error('no session');
  var path = __path(pathJson, 2);
  var head = path[0];
  if (!__own(SETTABLE, head) || SETTABLE[head] !== 'obj') throw new Error('cannot delete ' + path.join('.'));
  var allowed = SUB_SETTABLE[head];
  if (head === 'tune') {
    __mode(e, path[1]);
    if (path.length === 3) __tuneWindow(e, path[1], path[2]);
  } else {
    if (!__own(allowed, path[1]) || head !== 'faults' ||
        ['gcvStuck', 'purge'].indexOf(path[1]) < 0 || path.length !== 3 ||
        ['D5', 'PM1', 'PM3', 'PM2'].indexOf(path[2]) < 0) throw new Error('not deletable');
  }
  var o = e[head];
  for (var j = 1; j < path.length - 1; j++) { if (!__own(o, path[j])) return __stateJson(id, false); o = o[path[j]]; }
  delete o[path[path.length - 1]];
  return __stateJson(id, false);
}

/* the few methods a browser may call */
function __call(id, fn, argsJson) {
  var e = __S[id]; if (!e) throw new Error('no session');
  var args = JSON.parse(argsJson);
  if (!Array.isArray(args)) throw new Error('bad args');
  if (fn === 'setBlend' || fn === 'log') {
    if (args.length !== 1 || typeof args[0] !== 'string') throw new Error('one string argument expected');
    if (fn === 'setBlend') {
      if (!__own(DLN.FUEL_BLENDS, args[0])) throw new Error('unknown fuel blend');
      e.setBlend(args[0]);
    }
    else e.log(args[0].slice(0, 200));
  }
  else if (fn === 'resetTrip') {
    if (args.length) throw new Error('no arguments expected');
    e.resetTrip();
  }
  else if (fn === 'applyMapping') {
    if (typeof e.applyMapping !== 'function') throw new Error('saved mapping unavailable in this engine version');
    if (args.length !== 1 || !Array.isArray(args[0]) || args[0].length > 128) throw new Error('mapping point array expected (maximum 128)');
    args[0].forEach(function (point) {
      if (!__record(point) || Object.keys(point).sort().join(',') !== 'bias,mode,ttrf1' ||
          typeof point.ttrf1 !== 'number' || !isFinite(point.ttrf1) || !__record(point.bias)) {
        throw new Error('bad mapping point');
      }
      __mode(e, point.mode);
      Object.keys(point.bias).forEach(function (c) {
        var window = __tuneWindow(e, point.mode, c);
        var bias = point.bias[c];
        if (typeof bias !== 'number' || !isFinite(bias) || Math.abs(bias) > window + 1e-9) throw new Error('mapping bias outside tuning window');
      });
    });
    // Remaining engine-specific range and duplicate checks are atomic inside
    // the bundle. Only the learner's own schedule points cross this boundary.
    e.applyMapping(args[0]);
  }
  else if (fn === 'clearMapping') {
    if (args.length) throw new Error('no arguments expected');
    if (typeof e.clearMapping !== 'function') throw new Error('saved mapping unavailable in this engine version');
    e.clearMapping();
  }
  else if (fn === 'loadTrainingState') {
    if (args.length !== 1 || ['mapped', 'unmapped', 'unmapped_1', 'unmapped_2'].indexOf(args[0]) < 0) {
      throw new Error('one recognized training state expected');
    }
    if (typeof e.loadTrainingState !== 'function') throw new Error('training state selection unavailable in this engine version');
    if ((args[0] === 'unmapped_1' || args[0] === 'unmapped_2') &&
        ['scenario1', 'scenario2'].indexOf(e.trainingScenario) < 0) {
      throw new Error('training scenarios unavailable in this engine version');
    }
    // The protected engine owns the example schedule. The client selects a
    // named state; no preset coefficients or calibration cross this call.
    e.loadTrainingState(args[0]);
  }
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
    if (typeof DLN.respondingBands === 'function') {
      out[circuit] = DLN.respondingBands(modeKey, circuit, e.ttrf1, e.key);
      return;
    }
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

/* Only current-mode command offsets are display state. Do not serialize the
 * protected scenario definitions, helpers, or any unrecognized object keys. */
function __scenarioBias(e) {
  var bias = e.scenarioBias, out = {};
  if (!__record(bias)) return out;
  var md = e.deck && e.deck.modes && e.deck.modes[e.mode];
  if (!md || !md.schedules) return out;
  ['D5', 'PM1', 'PM3', 'PM2'].forEach(function (c) {
    if (__own(md.schedules, c) && __own(bias, c) && typeof bias[c] === 'number' && isFinite(bias[c])) out[c] = bias[c];
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
    mapPoints: Array.isArray(e.mapPoints) ? e.mapPoints : [], mapActive: !!e.mapActive,
    mappingSource: ['preset', 'learner', 'none'].indexOf(e.mappingSource) >= 0
      ? e.mappingSource : (e.mapActive ? 'learner' : 'none'),
    trainingScenario: ['scenario1', 'scenario2'].indexOf(e.trainingScenario) >= 0 ? e.trainingScenario : 'scenario1',
    scenarioBias: __scenarioBias(e),
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
