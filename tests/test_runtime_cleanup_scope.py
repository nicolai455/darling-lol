"""Cleanup scope regressions: fake proc/prefix trees and mocked signals only."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / 'tools/ensure-darling-runtime.py'


class RuntimeCleanupScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='cleanup-scope-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        self.prefix = self.root / 'selected prefix'
        self.other = self.root / 'unrelated prefix'
        self.shm = self.root / 'shm'
        for folder in (self.prefix / 'private/tmp', self.other / 'private/tmp', self.shm):
            folder.mkdir(parents=True)
        # Start the signal guard before importing, even though main is guarded.
        self.kill = self.enterContext(patch('os.kill'))
        spec = importlib.util.spec_from_file_location('cleanup_scope', SCRIPT)
        assert spec is not None and spec.loader is not None
        self.cleanup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cleanup)
        self.stderr = self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(patch.dict(os.environ, {'DPREFIX': str(self.prefix)}))
        self.enterContext(patch.object(self.cleanup, 'Path', side_effect=self.fake_path))

    def fake_path(self, value):
        # No cleanup code may read host /proc or touch host /dev/shm.
        return {'/proc': self.proc, '/dev/shm': self.shm}.get(str(value), Path(value))

    def process(self, pid, *, comm='launchd', argv=('/sbin/launchd',), state='S'):
        folder = self.proc / str(pid)
        folder.mkdir()
        (folder / 'comm').write_text(comm + '\n')
        (folder / 'cmdline').write_bytes(b'\0'.join(arg.encode() for arg in argv) + b'\0')
        (folder / 'status').write_text(f'State:\t{state} (fixture)\n')
        return folder

    def main(self):
        # Original default arguments contain /proc; always supply our fake root.
        server = self.cleanup.any_server_running
        launchd = self.cleanup.stop_orphaned_launchd
        crashpad = self.cleanup.stop_riot_crashpad
        with patch.object(self.cleanup, 'any_server_running', side_effect=lambda: server(self.proc)), \
                patch.object(self.cleanup, 'stop_orphaned_launchd', side_effect=lambda: launchd(self.proc)), \
                patch.object(self.cleanup, 'stop_riot_crashpad', side_effect=lambda: crashpad(self.proc)):
            self.cleanup.main()

    def test_same_uid_launchd_without_prefix_proof_is_not_killed(self):
        folder = self.process(991001)
        (folder / 'cmdline').write_bytes(b'/sbin/launchd' + b'\0' * 8)
        self.cleanup.stop_orphaned_launchd(self.proc)
        self.kill.assert_not_called()

    def test_guest_named_riot_and_league_crashpads_are_not_killed(self):
        for pid, bundle in enumerate(('Riot Client.app', 'League of Legends.app',
                                      'League of Legends (TM) Client.app'), 991010):
            with self.subTest(bundle=bundle):
                self.process(pid, comm='chrome_crashpad', argv=(
                    f'/Applications/{bundle}/Contents/Frameworks/chrome_crashpad_handler',))
                self.cleanup.stop_riot_crashpad(self.proc)
                self.kill.assert_not_called()

    def test_host_paths_in_either_prefix_do_not_prove_crashpad_ownership(self):
        for pid, prefix in enumerate((self.prefix, self.other), 991020):
            self.process(pid, comm='chrome_crashpad', argv=(str(
                prefix / 'Applications/Riot Client.app/Contents/MacOS/chrome_crashpad_handler'),))
        self.cleanup.stop_riot_crashpad(self.proc)
        self.kill.assert_not_called()

    def test_unrelated_browser_and_names_in_arguments_are_not_killed(self):
        self.process(991030, comm='chrome_crashpad', argv=(
            '/opt/browser/chrome_crashpad_handler', '/Applications/Riot Client.app/helper'))
        self.process(991031, comm='editor', argv=('/usr/bin/editor', '/sbin/launchd'))
        self.cleanup.stop_orphaned_launchd(self.proc)
        self.cleanup.stop_riot_crashpad(self.proc)
        self.kill.assert_not_called()

    def test_foreign_uid_processes_are_not_killed(self):
        self.process(991040)
        self.process(991041, comm='chrome_crashpad', argv=(
            '/Applications/Riot Client.app/chrome_crashpad_handler',))
        with patch.object(self.cleanup.os, 'getuid', return_value=os.getuid() + 1):
            self.cleanup.stop_orphaned_launchd(self.proc)
            self.cleanup.stop_riot_crashpad(self.proc)
        self.kill.assert_not_called()

    def test_disabled_cleanup_explains_manual_original_namespace_shutdown(self):
        root = Mock()
        root.iterdir.side_effect = AssertionError('disabled cleanup must not scan processes')
        self.cleanup.stop_orphaned_launchd(root)
        self.cleanup.stop_riot_crashpad(root)
        root.iterdir.assert_not_called()
        message = self.stderr.getvalue().lower()
        self.assertIn('ownership', message)
        self.assertIn('manual', message)
        self.assertIn('original', message)
        self.assertIn('namespace', message)
        self.kill.assert_not_called()

    def test_no_server_main_never_signals_and_preserves_unrelated_prefix(self):
        self.process(991050)
        self.process(991051, comm='chrome_crashpad', argv=(str(
            self.other / 'Applications/Riot Client.app/chrome_crashpad_handler'),))
        selected = self.prefix / 'private/tmp/.com.riotgames.selected'
        unrelated = self.other / 'private/tmp/.com.riotgames.other'
        shared = self.shm / 'darling-stale'
        ordinary = self.shm / 'unrelated-buffer'
        for file in (selected, unrelated, shared, ordinary):
            file.write_text('fixture')
        self.main()
        self.kill.assert_not_called()
        self.assertFalse(selected.exists())
        self.assertFalse(shared.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(ordinary.exists())

    def test_any_prefix_server_preserves_all_buffers(self):
        self.process(991060, comm='darlingserver', argv=(
            'darlingserver', '--prefix=' + str(self.other)))
        files = (self.prefix / 'private/tmp/.com.riotgames.selected', self.shm / 'darling-live')
        for file in files:
            file.write_text('fixture')
        self.main()
        self.kill.assert_not_called()
        for file in files:
            self.assertTrue(file.exists())

    def test_hidden_process_fails_closed_for_shared_buffers(self):
        hidden = Mock()
        hidden.name = '991070'
        hidden.__truediv__ = Mock(return_value=Mock())
        (hidden / 'comm').read_text.side_effect = PermissionError('hidden fixture')
        root = Mock()
        root.iterdir.return_value = [hidden]
        self.assertTrue(self.cleanup.any_server_running(root))
        with patch.object(self.cleanup, 'any_server_running', return_value=True), \
                patch.object(self.cleanup, 'remove_owned') as remove, \
                patch.object(self.cleanup, 'stop_orphaned_launchd') as launchd, \
                patch.object(self.cleanup, 'stop_riot_crashpad') as crashpad:
            self.cleanup.main()
        remove.assert_not_called()
        launchd.assert_not_called()
        crashpad.assert_not_called()
        self.kill.assert_not_called()

    def test_only_owned_regular_buffers_are_removed(self):
        owned = self.shm / 'darling-owned'
        owned.write_text('fixture')
        directory = self.shm / 'darling-directory'
        directory.mkdir()
        foreign = self.shm / 'darling-foreign'
        foreign.write_text('fixture')
        original_stat = Path.stat

        def stat(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            if path == foreign:
                values = list(result)
                values[4] = os.getuid() + 1
                return os.stat_result(values)
            return result

        with patch.object(Path, 'stat', stat):
            self.cleanup.remove_owned([owned, directory, foreign])
        self.assertFalse(owned.exists())
        self.assertTrue(directory.is_dir())
        self.assertTrue(foreign.exists())

    def test_missing_and_zombie_markers_are_archived_without_signals(self):
        for pid, state in ((991080, None), (991081, 'Z')):
            with self.subTest(state=state):
                if state:
                    self.process(pid, state=state)
                marker = self.prefix / '.init.pid'
                marker.write_text(str(pid))
                self.cleanup.recover_marker(self.prefix)
                self.assertFalse(marker.exists())
                archived = list(self.prefix.glob(f'.init.pid.stale-{pid}-*'))
                self.assertEqual(len(archived), 1)
                self.assertEqual(archived[0].read_text(), str(pid))
        self.kill.assert_not_called()

    def test_live_invalid_and_unreadable_markers_are_preserved(self):
        self.process(991090)
        marker = self.prefix / '.init.pid'
        for content in ('991090', 'not a pid', '0'):
            with self.subTest(content=content):
                marker.write_text(content)
                self.cleanup.recover_marker(self.prefix)
                self.assertEqual(marker.read_text(), content)
        marker.write_text('991090')
        original_read = Path.read_text

        def read(path, *args, **kwargs):
            if path == self.proc / '991090/status':
                raise PermissionError('fixture')
            return original_read(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            self.cleanup.recover_marker(self.prefix)
        self.assertEqual(marker.read_text(), '991090')
        self.kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
