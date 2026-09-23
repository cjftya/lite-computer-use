from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.lcu.apps import AppEntry, LaunchCandidate, app_status, is_matching_window, window_match_status
from scripts.lcu.ownership import owned_processes_for_window, remember_owned_processes
from scripts.lcu.processes import ProcessIdentity
from scripts.lcu.win_launch import DispatchReceipt, dispatch_shell
from scripts.lcu.app_resolver import LaunchSpec


@pytest.fixture(autouse=True)
def synthetic_interactive_session():
    with patch('scripts.lcu.processes.get_current_session_id', return_value=1), \
         patch('scripts.lcu.apps._candidate_target_is_stale', return_value=False):
        yield


def entry(path=r'C:\InstallA\Code.exe'):
    return AppEntry('vscode', path, 'config', ['Visual Studio Code'], 'vscode',
                    candidates=[LaunchCandidate(path, 'exe', 'config')])


def window(image=r'C:\InstallA\Code.exe', process='Code.exe', title='Visual Studio Code'):
    return {'hwnd': 101, 'pid': 202, 'title': title, 'process': process,
            'image_path': image, 'session_id': 1, 'creation_time': 55}


def test_titles_and_wrong_installation_are_not_identity():
    target = entry()
    assert window_match_status(window(r'C:\Program Files\Chrome\chrome.exe', 'chrome.exe',
                                      'Visual Studio Code - Google Chrome'), target) == 'no_match'
    assert window_match_status(window(r'C:\Tools\terminal.exe', 'terminal.exe',
                                      'Visual Studio Code terminal'), target) == 'no_match'
    assert window_match_status(window(r'D:\InstallB\Code.exe'), target) == 'no_match'
    assert window_match_status(window(image=None), target) == 'insufficient_evidence'
    assert is_matching_window(window(), target)


def test_shortcut_target_and_package_identity():
    shortcut = AppEntry('demo', r'C:\Menu\Demo.lnk', 'start-menu', [], 'demo',
                        candidates=[LaunchCandidate(r'C:\Menu\Demo.lnk', 'start-menu', 'start-menu',
                                                    expected_identity={'target_path': r'C:\Apps\demo.exe'})])
    assert is_matching_window(window(r'C:\Apps\demo.exe', 'demo.exe'), shortcut)
    assert not is_matching_window(window(r'C:\Other\demo.exe', 'demo.exe'), shortcut)
    packaged = AppEntry('calculator', r'shell:AppsFolder\Example.Calc!App', 'config', [], 'calculator')
    observed = window(r'C:\Program Files\WindowsApps\Calc\CalculatorApp.exe', 'CalculatorApp.exe')
    observed['app_user_model_id'] = 'Example.Calc!App'
    assert is_matching_window(observed, packaged)
    observed['app_user_model_id'] = 'Other.Calc!App'
    assert not is_matching_window(observed, packaged)


def test_browser_pwa_does_not_become_ready_from_process_and_title():
    browser = AppEntry('chrome', 'chrome.exe', 'config', ['Google Chrome'], 'chrome')
    assert window_match_status(window(r'C:\Chrome\chrome.exe', 'chrome.exe',
                                      'New Tab - Google Chrome'), browser) == 'insufficient_evidence'


@pytest.mark.parametrize('status,expected', [('accepted', True), ('rejected', False),
                                             ('unknown', None), (None, None), ('bogus', None)])
def test_app_status_preserves_dispatch_tristate(status, expected):
    payload = {'entry': entry().to_dict(), 'baseline_hwnds': [], 'dispatch': {'status': status}}
    with patch('scripts.lcu.apps.load_app_attempt', return_value=payload), \
         patch('scripts.lcu.apps._poll_for_launched_window', return_value=None), \
         patch('scripts.lcu.apps.dispatch_candidate') as dispatch:
        result = app_status('12345678-1234-1234-1234-123456789abc')
    assert result['dispatch_accepted'] is expected
    assert result['retry_launch_allowed'] is False
    assert json.loads(json.dumps(result))['dispatch_accepted'] is expected
    dispatch.assert_not_called()


def test_old_and_shell_ledger_evidence_cannot_authorize(tmp_path):
    ledger = tmp_path / 'ledger.json'
    identity = ProcessIdentity(202, 1, 'Code.exe', r'C:\InstallA\Code.exe', 55, 1).to_dict()
    old = {**identity, 'hwnd': 101, 'window_pid': 202, 'ownership_evidence': 'exact-dispatch-identity'}
    ledger.write_text(json.dumps({'version': 1, 'records': [old]}))
    with patch('scripts.lcu.ownership.get_ledger_path', return_value=ledger), \
         patch('scripts.lcu.ownership.is_same_process', return_value=True):
        assert owned_processes_for_window(101, 202) == []
        shell = {**old, 'dispatch_backend': 'shell-execute'}
        remember_owned_processes('vscode', 101, 202, [shell])
        assert owned_processes_for_window(101, 202) == []
        direct = {**old, 'dispatch_backend': 'process'}
        remember_owned_processes('vscode', 101, 202, [direct])
        assert len(owned_processes_for_window(101, 202)) == 1


def test_receipt_unknown_is_null():
    assert DispatchReceipt('unknown', 'shell-execute', 1).to_dict()['accepted'] is None


def test_shell_receipt_never_claims_direct_process_ownership():
    from scripts.lcu.apps import open_app
    identity = ProcessIdentity(202, 1, 'Code.exe', r'C:\InstallA\Code.exe', 55, 1)
    target = entry()
    found = window()
    with patch('scripts.lcu.apps.build_app_index', return_value=[target]), \
         patch('scripts.lcu.apps.find_matching_windows', return_value=[]), \
         patch('scripts.lcu.windows.list_windows', return_value=[]), \
         patch('scripts.lcu.apps._recheck_window', return_value=True), \
         patch('scripts.lcu.apps.snapshot_processes', side_effect=[{}, {202: identity}]), \
         patch('scripts.lcu.apps.dispatch_candidate', return_value={
             'status': 'accepted', 'backend': 'shell-execute',
             'dispatch_identity': identity.to_dict(), 'pid': 202,
         }), \
         patch('scripts.lcu.apps._poll_for_launched_window', return_value=found), \
         patch('scripts.lcu.windows.focus_window'), \
         patch('scripts.lcu.apps.save_app_attempt'), \
         patch('scripts.lcu.apps.remember_owned_processes') as remember:
        result = open_app('vscode')
    assert result['owned_processes'] == []
    remember.assert_not_called()


def test_direct_process_can_be_owned_with_complete_evidence():
    from scripts.lcu.apps import open_app
    identity = ProcessIdentity(202, 1, 'Code.exe', r'C:\InstallA\Code.exe', 55, 1)
    target = entry()
    with patch('scripts.lcu.apps.build_app_index', return_value=[target]), \
         patch('scripts.lcu.apps.find_matching_windows', return_value=[]), \
         patch('scripts.lcu.windows.list_windows', return_value=[]), \
         patch('scripts.lcu.apps._recheck_window', return_value=True), \
         patch('scripts.lcu.apps.snapshot_processes', side_effect=[{}, {202: identity}]), \
         patch('scripts.lcu.apps.dispatch_candidate', return_value={
             'status': 'accepted', 'backend': 'process',
             'dispatch_identity': identity.to_dict(), 'pid': 202,
         }), \
         patch('scripts.lcu.apps._poll_for_launched_window', return_value=window()), \
         patch('scripts.lcu.windows.focus_window'), \
         patch('scripts.lcu.apps.save_app_attempt'), \
         patch('scripts.lcu.apps.remember_owned_processes'):
        result = open_app('vscode')
    assert result['owned_processes'][0]['dispatch_backend'] == 'process'


def test_shell_com_rejection_and_balanced_uninitialize():
    import sys
    fake_com = MagicMock(COINIT_APARTMENTTHREADED=2)
    shell = MagicMock()
    shell.ShellExecuteExW.return_value = False
    with patch.dict(sys.modules, {'pythoncom': fake_com}), \
         patch('scripts.lcu.win_launch.os.name', 'nt'), \
         patch('scripts.lcu.win_launch.ctypes.WinDLL', return_value=shell, create=True), \
         patch('scripts.lcu.win_launch.ctypes.get_last_error', return_value=2, create=True), \
         patch('scripts.lcu.win_launch.ctypes.FormatError', return_value='missing', create=True), \
         patch('scripts.lcu.win_launch.ctypes.set_last_error', create=True):
        receipt = dispatch_shell(LaunchSpec('demo', 'shortcut', r'C:\Menu\demo.lnk'))
    assert receipt.status == 'rejected'
    fake_com.CoInitializeEx.assert_called_once_with(2)
    fake_com.CoUninitialize.assert_called_once()


def test_shell_com_initialization_failure_stops_before_dispatch():
    import sys
    fake_com = MagicMock(COINIT_APARTMENTTHREADED=2)
    fake_com.CoInitializeEx.side_effect = OSError('apartment mismatch')
    with patch.dict(sys.modules, {'pythoncom': fake_com}), \
         patch('scripts.lcu.win_launch.os.name', 'nt'), \
         patch('scripts.lcu.win_launch.ctypes.WinDLL', create=True) as dll:
        receipt = dispatch_shell(LaunchSpec('demo', 'uri', 'ms-settings:'))
    assert receipt.status == 'rejected'
    dll.assert_not_called()
    fake_com.CoUninitialize.assert_not_called()


def test_shell_success_keeps_accepted_when_identity_query_fails_and_closes_handle():
    import ctypes
    import sys
    fake_com = MagicMock(COINIT_APARTMENTTHREADED=2)
    shell = MagicMock()
    kernel = MagicMock()

    def accept(info_pointer):
        info = info_pointer._obj
        info.hProcess = 77
        return True

    shell.ShellExecuteExW.side_effect = accept
    kernel.GetProcessId.return_value = 202
    def dll(name, **kwargs):
        return shell if name == 'shell32' else kernel

    with patch.dict(sys.modules, {'pythoncom': fake_com}), \
         patch('scripts.lcu.win_launch.os.name', 'nt'), \
         patch('scripts.lcu.win_launch.ctypes.WinDLL', side_effect=dll, create=True), \
         patch('scripts.lcu.win_launch.ctypes.set_last_error', create=True), \
         patch('scripts.lcu.win_launch.get_process_identity', side_effect=OSError('denied')):
        receipt = dispatch_shell(LaunchSpec('demo', 'shortcut', r'C:\Menu\demo.lnk'))
    assert receipt.status == 'accepted'
    assert receipt.pid == 202
    assert 'denied' in receipt.message
    kernel.CloseHandle.assert_called_once_with(77)
    fake_com.CoUninitialize.assert_called_once()


def test_shell_call_exception_keeps_unknown_and_uninitializes():
    import sys
    fake_com = MagicMock(COINIT_APARTMENTTHREADED=2)
    shell = MagicMock()
    shell.ShellExecuteExW.side_effect = OSError('dispatch interrupted')
    with patch.dict(sys.modules, {'pythoncom': fake_com}), \
         patch('scripts.lcu.win_launch.os.name', 'nt'), \
         patch('scripts.lcu.win_launch.ctypes.WinDLL', return_value=shell, create=True), \
         patch('scripts.lcu.win_launch.ctypes.set_last_error', create=True):
        receipt = dispatch_shell(LaunchSpec('demo', 'uri', 'ms-settings:'))
    assert receipt.status == 'unknown'
    assert receipt.fallback_eligible is False
    fake_com.CoUninitialize.assert_called_once()


def test_focus_recheck_rejects_recycled_hwnd():
    from scripts.lcu.apps import _recheck_window
    previous = window()
    reused = {**previous, 'pid': 303, 'image_path': r'C:\InstallA\Code.exe'}
    with patch('scripts.lcu.windows.list_windows', return_value=[reused]):
        assert _recheck_window(previous, entry()) is False
    with patch('scripts.lcu.windows.list_windows', return_value=[previous]):
        assert _recheck_window(previous, entry()) is True


def test_two_verified_existing_windows_are_ambiguous_without_launch():
    from scripts.lcu.apps import open_app
    from scripts.lcu.errors import LCUError
    first = window()
    second = {**first, 'hwnd': 102}
    with patch('scripts.lcu.apps.build_app_index', return_value=[entry()]), \
         patch('scripts.lcu.windows.list_windows', return_value=[first, second]), \
         patch('scripts.lcu.apps.dispatch_candidate') as dispatch:
        with pytest.raises(LCUError) as raised:
            open_app('vscode')
    assert raised.value.code == 'ambiguous_target'
    dispatch.assert_not_called()


def test_unknown_dispatch_is_persisted_once_and_never_retried():
    from scripts.lcu.apps import open_app
    from scripts.lcu.errors import LCUError
    target = entry()
    with patch('scripts.lcu.apps.build_app_index', return_value=[target]), \
         patch('scripts.lcu.windows.list_windows', return_value=[]), \
         patch('scripts.lcu.apps.snapshot_processes', return_value={}), \
         patch('scripts.lcu.apps.dispatch_candidate', return_value={'status': 'unknown', 'backend': 'shell-execute'}) as dispatch, \
         patch('scripts.lcu.apps._poll_for_launched_window', return_value=None), \
         patch('scripts.lcu.apps.save_app_attempt') as save:
        with pytest.raises(LCUError) as raised:
            open_app('vscode')
    assert raised.value.details['dispatch_accepted'] is None
    assert raised.value.details['retry_launch_allowed'] is False
    assert save.call_args.args[1]['dispatch']['status'] == 'unknown'
    dispatch.assert_called_once()


def test_direct_process_identity_lookup_failure_keeps_accepted():
    from scripts.lcu.win_launch import dispatch_process
    process = MagicMock(pid=202)
    with patch('scripts.lcu.win_launch.subprocess.Popen', return_value=process), \
         patch('scripts.lcu.win_launch.os.name', 'nt'), \
         patch('scripts.lcu.win_launch.get_process_identity', side_effect=OSError('denied')), \
         patch('scripts.lcu.win_launch._cwd_for', return_value='.'):
        receipt = dispatch_process(LaunchSpec('demo', 'exe', 'demo.exe'), 'demo.exe')
    assert receipt.status == 'accepted'
    assert receipt.pid == 202
    assert receipt.dispatch_identity is None
