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


def test_named_training_state_preserves_operating_controls_and_private_configuration(runtime):
    for key, value in [('loadMW', 120), ('loadSetpoint', 150), ('tnh', 100),
                       ('ttrf1', 2250), ('ftg', 95), ('ctim', 80), ('sh', 0.004),
                       ('breaker', True)]:
        write(runtime, [key], value)
    write(runtime, ['tune', 'D5', 'PM3'], 0.75)
    before = invoke(runtime, '__stateJson', 'one', False)
    runtime.eval("__S.one.trainingPreset = {privateMarker: 'protected-preset-marker'};")
    mapped = invoke(runtime, '__call', 'one', 'loadTrainingState', '["mapped"]')
    assert mapped['mappingSource'] == 'preset' and mapped['mapActive']
    assert mapped['mapPoints'] == [{'mode': 'D5', 'ttrf1': 1000, 'bias': {'PM3': 0.5}}]
    assert mapped['tune'] == {}
    for key in ('t', 'mode', 'loadMW', 'loadSetpoint', 'tnh', 'ttrf1', 'ftg', 'ctim', 'sh', 'breaker'):
        assert mapped[key] == before[key]
    assert 'protected-preset-marker' not in json.dumps(mapped)
    assert 'trainingPreset' not in mapped and 'resp' not in mapped
    assert invoke(runtime, '__stateJson', 'two', False)['mappingSource'] == 'none'
    with pytest.raises(Exception):
        write(runtime, ['mappingSource'], 'preset')
    unmapped = invoke(runtime, '__call', 'one', 'loadTrainingState', '["unmapped"]')
    assert unmapped['mappingSource'] == 'none' and not unmapped['mapActive']
    assert unmapped['mapPoints'] == [] and unmapped['tune'] == {}
    assert invoke(runtime, '__new', 'one', '9FA', 'multi', 'tuning')['state']['mappingSource'] == 'none'


@pytest.mark.parametrize('args', [[], ['reference'], ['constructor'], ['__proto__'],
                                  [None], [True], [{}], ['mapped', 'unmapped'], 'mapped'])
def test_training_state_refuses_malformed_or_unrecognized_selections(runtime, args):
    before = invoke(runtime, '__stateJson', 'one', False)
    with pytest.raises(Exception):
        invoke(runtime, '__call', 'one', 'loadTrainingState', json.dumps(args))
    assert invoke(runtime, '__stateJson', 'one', False) == before


def test_training_state_reports_older_bundle_unavailable_without_changing_session(runtime):
    runtime.eval('delete DLN.Engine.prototype.loadTrainingState; delete __S.one.mappingSource;')
    with pytest.raises(Exception, match='training state selection unavailable'):
        invoke(runtime, '__call', 'one', 'loadTrainingState', '["mapped"]')
    assert invoke(runtime, '__stateJson', 'one', False)['mappingSource'] == 'none'
    runtime.eval('__S.one.mapActive = true; __S.one.mappingSource = {secret: 1};')
    assert invoke(runtime, '__stateJson', 'one', False)['mappingSource'] == 'learner'
    assert invoke(runtime, '__tick', 'one', 1, False)['frames'][0]['t'] == 1


def test_named_preset_does_not_overload_user_mapping_arguments(runtime):
    with pytest.raises(Exception, match='mapping point array expected'):
        invoke(runtime, '__call', 'one', 'applyMapping', '["mapped"]')


def test_scenario_selection_and_mapping_keep_only_current_public_metadata(runtime):
    # Synthetic fixture values only. Real scenario definitions remain private.
    runtime.eval("__S.one.trainingScenarios = {secret: 'private-scenario-sentinel'};")
    selected = invoke(runtime, '__call', 'one', 'loadTrainingState', '["unmapped_2"]')
    assert selected['trainingScenario'] == 'scenario2'
    assert selected['scenarioBias'] == {'PM3': 0.4}
    assert 'private-scenario-sentinel' not in json.dumps(selected)
    assert invoke(runtime, '__stateJson', 'two', False)['trainingScenario'] == 'scenario1'
    mapped = invoke(runtime, '__call', 'one', 'loadTrainingState', '["mapped"]')
    assert mapped['trainingScenario'] == 'scenario2' and mapped['mapActive']
    cleared = invoke(runtime, '__call', 'one', 'clearMapping', '[]')
    assert cleared['trainingScenario'] == 'scenario2' and not cleared['mapActive']
    assert cleared['scenarioBias'] == {'PM3': 0.4}
    for name in ['unmapped_1', 'unmapped']:
        invoke(runtime, '__call', 'one', 'loadTrainingState', '["unmapped_2"]')
        reset = invoke(runtime, '__call', 'one', 'loadTrainingState', json.dumps([name]))
        assert reset['trainingScenario'] == 'scenario1' and reset['scenarioBias'] == {}
    invoke(runtime, '__call', 'one', 'loadTrainingState', '["unmapped_2"]')
    fresh = invoke(runtime, '__new', 'one', '9FA', 'multi', 'tuning')['state']
    assert fresh['trainingScenario'] == 'scenario1' and fresh['scenarioBias'] == {}


@pytest.mark.parametrize('path,value', [
    (['trainingScenario'], 'scenario2'), (['scenarioBias'], {'PM3': 0.4}),
    (['scenarioBias', 'PM3'], 0.4), (['training_scenarios'], {}),
])
def test_scenario_metadata_is_not_client_settable(runtime, path, value):
    before = invoke(runtime, '__stateJson', 'one', False)
    with pytest.raises(Exception, match='not settable'):
        write(runtime, path, value)
    assert invoke(runtime, '__stateJson', 'one', False) == before


def test_scenario_snapshot_filters_extra_private_fields_and_legacy_functions(runtime):
    runtime.eval("__S.one.trainingScenario = {secret: 1}; __S.one.scenarioBias = {PM3: 0.4, PM1: 9, secret: 'private', D5: NaN};")
    snap = invoke(runtime, '__stateJson', 'one', False)
    assert snap['trainingScenario'] == 'scenario1' and snap['scenarioBias'] == {'PM3': 0.4}
    runtime.eval("__S.one.scenarioBias = function() { return {secret: 1}; };")
    assert invoke(runtime, '__stateJson', 'one', False)['scenarioBias'] == {}


def test_older_bundle_refuses_scenario_aliases_without_mutation(runtime):
    runtime.eval('delete __S.one.trainingScenario; delete __S.one.scenarioBias;')
    before = invoke(runtime, '__stateJson', 'one', False)
    for name in ['unmapped_1', 'unmapped_2']:
        with pytest.raises(Exception, match='training scenarios unavailable'):
            invoke(runtime, '__call', 'one', 'loadTrainingState', json.dumps([name]))
        assert invoke(runtime, '__stateJson', 'one', False) == before
    assert invoke(runtime, '__call', 'one', 'loadTrainingState', '["mapped"]')['mappingSource'] == 'preset'
