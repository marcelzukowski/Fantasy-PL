"""Bounded audit reproductions; all persistent writes stay beside this script."""
import ctypes
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QProcess
from desktop_app.manual_scenario_store import ScenarioStore
from desktop_app.main_window import MainWindow
from fpl_engine.planning.context import _file_sha256

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
app = QCoreApplication([])
results = {}

# Copy an existing result, retaining its real context/input identity and path.
source = json.loads((ROOT/'scratch/manual_comparator_20261023/source_smoke.json').read_text())
result = source['cases']['HOLD']['result']
original = result['scenario']['objective']
result['scenario']['objective'] = original + 100
store = ScenarioStore(HERE/'scenario-result-probe.json')
store.save('Audit inconsistent objective', [], [], result['context_id'], result['input_sha256'], result)
loaded = store.load()[0]['result']['scenario']
reconstructed = sum(step['lineup_points']-step['hit_points'] for step in loaded['path']) + loaded['terminal_ft_value']
results['saved_result_consistency'] = {'accepted_inconsistent_result': loaded['objective'] != reconstructed, 'claimed_objective': loaded['objective'], 'reconstructed_objective': reconstructed}

# Stat-keyed hashes trust a mutable file's size and modification timestamp.
probe = HERE/'hash-cache-probe.bin'
probe.write_bytes(b'original')
first = _file_sha256(probe)
stat = probe.stat()
probe.write_bytes(b'mutation')
os.utime(probe, ns=(stat.st_atime_ns, stat.st_mtime_ns))
cached, actual = _file_sha256(probe), sha256(probe.read_bytes()).hexdigest()
results['stat_hash_cache'] = {'same_size_mtime_rewrite_accepted_by_cache': first == cached and cached != actual}

# Real FailedToStart: Qt does not emit finished; production callbacks only log.
logs, finished = [], []
holder = SimpleNamespace(_append_engine_log=logs.append, decision_run_state='RUNNING', chip_run_state='RUNNING')
process = QProcess()
process.errorOccurred.connect(lambda error: MainWindow._decision_process_error(holder, error))
process.finished.connect(lambda *args: finished.append(args))
process.start(str(HERE/'deliberately-missing-worker.exe'))
started = process.waitForStarted(500)
app.processEvents()
MainWindow._chip_process_error(holder, QProcess.ProcessError.FailedToStart)
results['worker_failed_to_start'] = {'started': started, 'error_logged': bool(logs), 'finished_emitted': bool(finished), 'state_after_callback': holder.decision_run_state, 'chip_state_after_callback':holder.chip_run_state}

# Windows venv redirector: test, rather than assume, a lifetime issue.
if os.name == 'nt':
    process = QProcess()
    process.start(str(ROOT/'.venv/Scripts/python.exe'), ['-c', 'import os,time; print(os.getpid(),flush=True); time.sleep(2)'])
    assert process.waitForStarted(3000) and process.waitForReadyRead(3000)
    child_pid = int(bytes(process.readAllStandardOutput()).strip())
    launcher_pid = process.processId()
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p,ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000,False,child_pid)
    assert handle
    try:
        process.kill()
        assert process.waitForFinished(1000)
        survived = kernel.WaitForSingleObject(handle,150) == 258
        natural_exit = kernel.WaitForSingleObject(handle,5000) == 0
        results['windows_worker_lifetime'] = {'launcher_and_child_differ': launcher_pid != child_pid, 'child_survived_launcher_kill': survived, 'child_exited_by_cleanup_deadline': natural_exit}
        assert natural_exit
    finally:
        kernel.CloseHandle(handle)

assert results['saved_result_consistency']['accepted_inconsistent_result']
assert results['stat_hash_cache']['same_size_mtime_rewrite_accepted_by_cache']
assert not results['worker_failed_to_start']['started']
assert not results['worker_failed_to_start']['finished_emitted']
(HERE/'operational-probes.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print(json.dumps(results,indent=2))
