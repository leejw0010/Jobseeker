"""Offline exports must reject contamination and preserve failed-run denominators."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from evals.validation.compare import compare, validate


def artifact(run='one', status='complete', passed=False):
    return dict(schemaVersion='jobseeker-validation-v1', kind='gaze-phase0', evidence='synthetic-signal',
                runId=run, protocolVersion='gaze-phase0-v2', methodVersion='gaze-existing-v1', configVersion='gaze-thresholds-v1', codeVersion='abc', dirty=True,
                status=status, reasonCodes=[], environment=dict(browser='chromium', condition='baseline', delegate='CPU'),
                denominators=dict(attempts=1, observed=100, accepted=80), metrics=dict(e50Relative=.1), verdicts=dict(h2='pass' if passed else 'fail'))


def test_failed_complete_remains_in_denominator_and_invalid_separate():
    group = compare([artifact(), artifact('two', passed=True), artifact('three', 'invalid')])['groups'][0]
    assert group['complete'] == 2 and group['invalid'] == 1
    assert group['verdicts']['h2'] == dict(passCount=1, denominator=2, passRate=.5)


def test_incompatible_config_or_evidence_are_separate():
    a = artifact(); b = artifact('two'); b['configVersion']='other'
    c=artifact('three'); c['evidence']='human-device'
    assert len(compare([a,b,c])['groups']) == 3


@pytest.mark.parametrize('mutate', [lambda a:a.update(reasonCodes=['raw error secret']), lambda a:a.update(schemaVersion='future'), lambda a:a['metrics'].update(e50Relative=float('nan')),
    lambda a:a['denominators'].update(observed=-1), lambda a:a['denominators'].update(accepted=101),
    lambda a:a.update(transcript='secret'), lambda a:a['metrics'].update(rawFrame=1), lambda a:a['environment'].update(token='secret')])
def test_rejects_unsafe_or_invalid_export(mutate):
    a=artifact(); mutate(a)
    with pytest.raises(ValueError):validate(a)


def test_duplicate_run_ids_rejected():
    with pytest.raises(ValueError, match='duplicate'):compare([artifact(),artifact()])


def test_repeat_spread_is_reference_only():
    rows=[artifact(str(i)) for i in range(3)]
    for a, v in zip(rows, [.1,.2,.3]):a['metrics']['e50Relative']=v
    g=compare(rows)['groups'][0]
    assert g['repeatSpreadReference'] == pytest.approx(1)
    assert g['h2OverallCertified'] is False


def test_cli_writes_new_output_and_legacy_is_separate(tmp_path):
    source=tmp_path/'run.json';source.write_text(json.dumps([artifact(),dict(note='old',runs=[{'g2.e50Pct':.2}])]))
    out=tmp_path/'result'
    p=subprocess.run([sys.executable,'-m','evals.validation.compare','--input',str(source),'--out',str(out)],capture_output=True,text=True,cwd=Path(__file__).parents[1])
    assert p.returncode == 0,p.stderr
    assert {f.name for f in out.iterdir()}=={'comparison.json','comparison.csv','comparison.md'}
    assert json.loads((out/'comparison.json').read_text())['legacyUnversionedCount']==1
    assert subprocess.run([sys.executable,'-m','evals.validation.compare','--input',str(source),'--out',str(out)],capture_output=True,cwd=Path(__file__).parents[1]).returncode!=0

@pytest.mark.parametrize('metrics', [dict(samples=1.5),dict(coverage=1.2),dict(analyzedMs=100,inMs=30,edgeMs=20,noneMs=100),dict(detectedMs=30,inMs=30,edgeMs=20)])
def test_rejects_inconsistent_metric_counts_and_ratios(metrics):
    a=artifact();a['metrics']=metrics
    with pytest.raises(ValueError):validate(a)
