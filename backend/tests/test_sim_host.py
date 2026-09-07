"""Generic host boundaries; no private engine, calibration, or source data."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from py_mini_racer import MiniRacer

from test_sim_engine import FAKE_ENGINE


@pytest.fixture
def runtime():
    ctx = MiniRacer()
    ctx.eval('var window = globalThis;')
    ctx.eval(FAKE_ENGINE)
    ctx.eval((Path(__file__).parents[1] / 'app' / 'sim_host.js').read_text(encoding='utf-8'))
    invoke(ctx, '__new', 'one', '9FA', 'multi', 'tuning')
    invoke(ctx, '__new', 'two', '9FB', 'single', 'tuning')
    yield ctx
    ctx.close()


def invoke(ctx, fn, *args):
    value = ctx.eval(f"{fn}({','.join(json.dumps(arg) for arg in args)})")
    return json.loads(value) if isinstance(value, str) else value


def write(ctx, path, value):
    return invoke(ctx, '__set', 'one', json.dumps(path), json.dumps(value))


@pytest.mark.parametrize('path', [
    ['tune', '__proto__', 'polluted'], ['tune', 'constructor', 'polluted'],
    ['faults', '__proto__', 'polluted'], ['faults', 'constructor', 'polluted'],
    ['tune', 'D5', '__proto__'], ['tune', 'D5', 'constructor'],
    ['__proto__'], ['constructor'], ['toString'],
])
def test_prototype_paths_are_refused_without_cross_session_changes(runtime, path):
    with pytest.raises(Exception):
        write(runtime, path, 1)
    if len(path) >= 2:
        with pytest.raises(Exception):
            invoke(runtime, '__del', 'one', json.dumps(path))
    assert runtime.eval('Object.prototype.polluted === undefined')
    assert runtime.eval('typeof Object.prototype.toString') == 'function'
    assert invoke(runtime, '__stateJson', 'two', False)['tune'] == {}


def test_tune_writes_use_the_deck_window_and_reject_partial_invalid_updates(runtime):
    assert write(runtime, ['tune', 'D5', 'PM3'], 20)['tune'] == {'D5': {'PM3': 1}}
    assert write(runtime, ['tune', 'D5'], {'PM3': -20})['tune'] == {'D5': {'PM3': -1}}
    for path, value in [
        (['tune', 'D5'], {'PM3': 0.5, 'BAD': 1}),
        (['tune', 'D5'], {'PM3': 0.5, '__proto__': 1}),
        (['tune', 'unknown', 'PM3'], 0.5),
        (['tune', 'D5', 'PM3'], '1'),
        (['tune', 'D5', 'PM3'], None),
        (['tune', 'D5', 'PM3'], []),
        (['tune'], []),
        (['tune'], {'D5': {'PM3': 0.5}}),
    ]:
        with pytest.raises(Exception):
            write(runtime, path, value)
        assert invoke(runtime, '__stateJson', 'one', False)['tune'] == {'D5': {'PM3': -1}}
    assert write(runtime, ['tune'], {})['tune'] == {}


def test_tuning_delegates_total_window_clamping_to_new_engine(runtime):
    # This stand-in has a learner map baseline of +0.4, so its +1 window
    # permits only +0.6 manual trim. No proprietary model is needed here.
    runtime.eval("""
    DLN.Engine.prototype.setTuneBias = function(mode, circuit, value) {
      this.tune[mode] = this.tune[mode] || {};
      this.tune[mode][circuit] = Math.max(-1.4, Math.min(0.6, value));
    };
    """)
    assert write(runtime, ['tune', 'D5', 'PM3'], 20)['tune']['D5']['PM3'] == 0.6
    assert write(runtime, ['tune', 'D5'], {'PM3': -20})['tune']['D5']['PM3'] == -1.4


def test_machine_specific_response_uses_engine_helper_with_legacy_fallback(runtime):
    assert invoke(runtime, '__stateJson', 'one', False)['responding']['PM3'] == {'31-122': 0.5}
    runtime.eval("""
    DLN.respondingBands = function(mode, circuit, ttrf1, machine) {
      return circuit === 'PM3' ? {'31-122': machine === '9FA' ? -0.2 : 0.3} : {};
    };
    """)
    assert invoke(runtime, '__stateJson', 'one', False)['responding']['PM3'] == {'31-122': -0.2}
    assert invoke(runtime, '__stateJson', 'two', False)['responding']['PM3'] == {'31-122': 0.3}


def test_calls_refuse_inherited_fuel_names_and_wrong_argument_shapes(runtime):
    for fn, args in [('setBlend', ['constructor']), ('setBlend', ['__proto__']),
                     ('setBlend', ['unknown']), ('setBlend', [{}]),
                     ('resetTrip', [1]), ('log', []), ('log', {})]:
        with pytest.raises(Exception):
            invoke(runtime, '__call', 'one', fn, json.dumps(args))
    assert invoke(runtime, '__stateJson', 'one', False)['blend'] == 'site gas (design)'
    assert invoke(runtime, '__tick', 'one', 1, False)['frames'][0]['t'] == 1


def test_mapping_calls_are_versioned_validated_and_expose_only_user_points(runtime):
    point = {'mode': 'D5', 'ttrf1': 1000, 'bias': {'PM3': 0.5}}
    runtime.eval('delete DLN.Engine.prototype.applyMapping; delete DLN.Engine.prototype.clearMapping;')
    with pytest.raises(Exception, match='saved mapping unavailable'):
        invoke(runtime, '__call', 'one', 'applyMapping', json.dumps([[point]]))
    runtime.eval("""
    DLN.Engine.prototype.applyMapping = function(points) {
      this.mapPoints = points; this.mapActive = true; this.tune = {};
    };
    DLN.Engine.prototype.clearMapping = function() {
      this.mapPoints = []; this.mapActive = false; this.tune = {};
    };
    """)
    state = invoke(runtime, '__call', 'one', 'applyMapping', json.dumps([[point]]))
    assert state['mapPoints'] == [point] and state['mapActive']
    assert 'secret' not in state and 'resp' not in state
    for points in [
        [dict(point, extra='untrusted')],
        [dict(point, bias={'PM3': 20})],
        [dict(point, bias={'constructor': 1})],
        [dict(point, mode='__proto__')],
        [dict(point, ttrf1='1000')],
        [point] * 129,
    ]:
        with pytest.raises(Exception):
            invoke(runtime, '__call', 'one', 'applyMapping', json.dumps([points]))
        assert invoke(runtime, '__stateJson', 'one', False)['mapPoints'] == [point]
    with pytest.raises(Exception):
        invoke(runtime, '__call', 'one', 'clearMapping', '[1]')
    edge = dict(point, bias={'PM3': 1 + 5e-10})
    assert invoke(runtime, '__call', 'one', 'applyMapping', json.dumps([[edge]]))['mapPoints'] == [edge]
    cleared = invoke(runtime, '__call', 'one', 'clearMapping', '[]')
    assert not cleared['mapActive'] and cleared['mapPoints'] == []
    assert invoke(runtime, '__new', 'one', '9FA', 'multi', 'tuning')['state']['mapPoints'] == []


@pytest.mark.parametrize('path,value', [
    (['breaker'], {}), (['instr', 'fieldVariation'], {}),
    (['faults', 'pm2Broken'], 'false'), (['prot', 'purgeFault'], 1e9),
    (['faults', 'gcvStuck'], None), (['faults', 'purge', 'D5'], 'unknown'),
    (['faults', 'gcvStuck', 'unknown'], 8),
])
def test_malformed_state_writes_are_refused_and_engine_remains_usable(runtime, path, value):
    with pytest.raises(Exception):
        write(runtime, path, value)
    assert invoke(runtime, '__tick', 'one', 1, False)['frames'][0]['t'] == 1
