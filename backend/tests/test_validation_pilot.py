"""The human pilot launcher checks isolation without opening devices or loading a model."""
import subprocess
from pathlib import Path


def test_pilot_check_uses_fresh_tmp_storage_without_starting_services():
    root=Path(__file__).parents[2]
    command=root/'scripts/start-validation-pilot.sh'
    result=subprocess.run([str(command),'--check'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'Fresh isolated pilot: /tmp/jobseeker-human-pilot-' in result.stdout
    assert '8013' in result.stdout and '5181' in result.stdout
    path=result.stdout.splitlines()[0].removeprefix('Fresh isolated pilot: ')
    assert not Path(path).exists()
