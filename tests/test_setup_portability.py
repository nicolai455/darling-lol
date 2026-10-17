"""Filesystem/subprocess fixtures: never invoke a host runtime or compiler."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


VALIDATION_INPUTS = (
    'libDarlingXShm.dylib',
    *(f'RuntimeLibraries/{name}.dylib' for name in (
        'libsystem_kernel', 'libsystem_c', 'libsystem_platform', 'libsystem_malloc',
        'libsystem_pthread', 'libobjc.A', 'libc++abi', 'libc++.1',
        'libGL', 'libindium', 'libiridium')),
    *(f'RuntimeFrameworks/{name}.framework/Versions/{version}/{name}' for name, version in (
        ('AppKit', 'C'), ('QuartzCore', 'A'), ('CoreFoundation', 'A'),
        ('SystemConfiguration', 'A'), ('CFNetwork', 'A'), ('IOSurface', 'A'),
        ('OpenGL', 'A'), ('CoreVideo', 'A'), ('CoreAudio', 'A'), ('AudioToolbox', 'A'),
        ('CoreGraphics', 'A'), ('CoreText', 'A'), ('Metal', 'A'), ('CarbonCore', 'A'),
        ('LaunchServices', 'A'))),
    'RuntimeFrameworks/AppKit.framework/Versions/C/Resources/Backends/X11.backend/Contents/MacOS/X11',
    'RuntimeFrameworks/OpenGL.framework/Versions/A/Libraries/libGL.dylib',
    'Library/Audio/Plug-Ins/Components/DarlingRiotAudio.component/Contents/MacOS/CoreAudio',
)


class SetupFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='setup fixture ', dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project space'
        self.root.mkdir()
        for name in ('scripts', 'tools'):
            shutil.copytree(ROOT / name, self.root / name)
        self.home = Path(self.tmp.name) / 'host home'
        self.home.mkdir()
        self.prefix = Path(self.tmp.name) / 'custom prefix'
        self.guest = self.prefix / 'Users/Guest Account'
        self.bin = Path(self.tmp.name) / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), TMPDIR=self.tmp.name,
                        DPREFIX=str(self.prefix), PYTHONDONTWRITEBYTECODE='1',
                        PATH=str(self.bin) + ':' + os.environ['PATH'])
        self.config = dict(project_root=str(self.root), host_home=str(self.home),
                           prefix=str(self.prefix), guest_user='Guest Account',
                           guest_home='/Users/Guest Account', sdk=str(self.root / 'sdk'), jobs=1)
        (self.root / 'build').mkdir()
        (self.root / 'build/config.json').write_text(json.dumps(self.config))
        self.log = Path(self.tmp.name) / 'events'
        self.env['FIXTURE_LOG'] = str(self.log)

    def run_script(self, path, *args):
        return subprocess.run([sys.executable if path.endswith('.py') else 'sh',
                               str(self.root / path), *args], env=self.env,
                              text=True, capture_output=True, timeout=20)

    def configure(self):
        result = self.run_script('scripts/configure.py')
        self.assertEqual(result.returncode, 0, result.stderr)

    def stub(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\nset -eu\n' + body + '\n')
        path.chmod(0o755)

    def runtime_stubs(self):
        # Nested Python is a strict allowlist: no accidental live helper execution.
        self.stub('python3', '''printf 'python %s\\n' "$*" >> "$FIXTURE_LOG"
case "$1" in
 -) exec REAL_PYTHON "$@";;
 *stop-darling-runtime.py) [ "${STOP_FAIL:-0}" = 0 ] || exit 9; printf stopped\\n >> "$FIXTURE_LOG";;
 *build-*.py|*ensure-darling-runtime.py|*install-darling-system-profiler.py|*install-riot-*.py) :;;
 *) exit 90;;
esac'''.replace('REAL_PYTHON', sys.executable))
        self.stub('darling', '''printf 'darling %s\\n' "$*" >> "$FIXTURE_LOG"
if [ "$1" = shutdown ]; then sleep "${SHUTDOWN_DELAY:-0}"; exit "${SHUTDOWN_FAIL:-0}"; fi''')
        self.stub('clang', '''last=; for arg do if [ "$last" = -o ]; then printf binary > "$arg"; fi; last=$arg; done''')
        self.stub('sudo', 'exit 1')
        self.stub('make', ':')
        self.stub('cc', 'exec clang "$@"')
        self.stub('pkg-config', ':')
        self.stub('install', '''case "$(cat "$FIXTURE_LOG")" in *stopped*) :;; *) exit 88;; esac
exec REAL_INSTALL "$@"'''.replace('REAL_INSTALL', shutil.which('install')))

    def presentation_inputs(self):
        for name in ('external/cocotron/AppKit/AppKit', 'external/cocotron/AppKit/X11',
                     'external/cocotron/QuartzCore/QuartzCore',
                     'external/corefoundation/CoreFoundation',
                     'external/configd/SystemConfiguration.fproj/SystemConfiguration',
                     'external/cfnetwork/src/CFNetwork',
                     'external/libplatform/libsystem_platform.dylib',
                     'external/xnu/darling/src/libsystem_kernel/libsystem_kernel.dylib'):
            path = self.root / 'build/darling-src/build/src' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('library')
        for framework, version in (('AppKit', 'C'), ('QuartzCore', 'A'),
                                   ('CoreFoundation', 'A'), ('SystemConfiguration', 'A'),
                                   ('CFNetwork', 'A')):
            path = self.root / 'sdk/System/Library/Frameworks' / (framework + '.framework')
            binary = path / 'Versions' / version / framework
            binary.parent.mkdir(parents=True)
            binary.write_text('sdk binary')
            binary.chmod(0o555)
            (path / 'Versions/Current').symlink_to(version)
            (path / framework).symlink_to('Versions/Current/' + framework)
            if framework == 'AppKit':
                backend = binary.parent / 'Resources/Backends/X11.backend/Contents/MacOS/X11'
                backend.parent.mkdir(parents=True)
                backend.write_text('sdk backend')
        p = self.root / 'build/libcxx-install/lib'
        p.mkdir(parents=True)
        (p / 'libc++.1.0.dylib').write_text('library')

    def test_configure_replaces_readonly_and_repeats(self):
        self.configure()
        generated = self.root / 'build/runtime/tools/run-riot-client.sh'
        generated.chmod(0o444)
        self.configure()
        self.configure()
        self.assertTrue(generated.stat().st_mode & 0o200)

    def test_configure_unlinks_dangling_symlink_without_writing_victim(self):
        self.configure()
        target = self.root / 'build/runtime/tools/run-riot-client.sh'
        target.unlink()
        victim = self.home / 'must not be created'
        target.symlink_to(victim)
        self.configure()
        self.assertFalse(victim.exists(), 'configure followed the dangling generated-file symlink')
        self.assertFalse(target.is_symlink())

    def test_configure_unlink_error_aborts_without_write(self):
        self.configure()
        spec = importlib.util.spec_from_file_location('fixture_common', self.root / 'scripts/common.py')
        assert spec is not None and spec.loader is not None
        common = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(common)
        target = self.root / 'build/runtime/tools/run-riot-client.sh'
        before = target.read_bytes()
        real_unlink = Path.unlink
        def unlink(path, *args, **kwargs):
            if path == target:
                raise PermissionError('fixture unlink failure')
            return real_unlink(path, *args, **kwargs)
        import runpy
        with patch.dict(sys.modules, {'common': common}), patch.object(Path, 'unlink', unlink), \
                patch.object(sys, 'argv', ['configure.py']), patch.dict(os.environ, self.env):
            with self.assertRaisesRegex(PermissionError, 'fixture unlink failure'):
                runpy.run_path(str(self.root / 'scripts/configure.py'), run_name='__main__')
        self.assertEqual(target.read_bytes(), before)

    def test_presentation_creates_prerequisites_and_repeat_install(self):
        self.configure()
        self.runtime_stubs()
        self.presentation_inputs()
        for _ in range(2):
            result = self.run_script('build/runtime/tools/install-riot-presentation-runtime.sh')
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.guest / 'libDarlingXShm.dylib').is_file())
        self.assertTrue((self.guest / 'RuntimeLibraries/libsystem_kernel.dylib').is_file())
        self.assertIn('stopped', self.log.read_text())

    def test_presentation_without_build_directory(self):
        self.configure()
        self.runtime_stubs()
        # Build outputs are stubbed, but clang's output creation is real.
        shutil.rmtree(self.root / 'build')
        (self.root / 'build').mkdir()  # execute the rendered copy detached from config
        rendered = self.root / 'tools/install-riot-presentation-runtime.sh'
        rendered.write_text((ROOT / 'tools/install-riot-presentation-runtime.sh').read_text()
                            .replace('@DPREFIX@', str(self.prefix))
                            .replace('@DARLING_SDK@', str(self.root / 'sdk'))
                            .replace('@GUEST_HOME@', '/Users/Guest Account'))
        helper = self.root / 'tools/runtime-paths.sh'
        helper.write_text(helper.read_text().replace('@DPREFIX@', str(self.prefix))
                          .replace('@GUEST_HOME@', '/Users/Guest Account'))
        result = self.run_script('tools/install-riot-presentation-runtime.sh')
        self.assertTrue((self.root / 'build/libDarlingXShm.next.dylib').is_file(), result.stderr)
        self.assertNotEqual(result.returncode, 0)  # expected library inputs are absent

    def test_presentation_configured_prefix_without_environment_and_runtime_override(self):
        self.configure()
        self.runtime_stubs()
        self.presentation_inputs()
        self.env.pop('DPREFIX')
        result = self.run_script('build/runtime/tools/install-riot-presentation-runtime.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.guest / 'RuntimeLibraries/libsystem_kernel.dylib').is_file())
        alternate = Path(self.tmp.name) / 'different runtime prefix'
        self.env['DPREFIX'] = str(alternate)
        result = self.run_script('build/runtime/tools/install-riot-presentation-runtime.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((alternate / 'Users/Guest Account/RuntimeLibraries/libsystem_kernel.dylib').is_file())
        self.assertFalse((self.home / '.darling').exists())

    def test_failed_stop_does_not_replace_overlay(self):
        self.configure()
        self.runtime_stubs()
        self.presentation_inputs()
        self.guest.mkdir(parents=True)
        sentinel = self.guest / 'libDarlingXShm.dylib'
        sentinel.write_text('unchanged')
        self.env.update(STOP_FAIL='1', SHUTDOWN_FAIL='1')
        result = self.run_script('build/runtime/tools/install-riot-presentation-runtime.sh')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(sentinel.read_text(), 'unchanged')

    def test_custom_guest_override(self):
        self.configure()
        self.runtime_stubs()
        self.presentation_inputs()
        override = self.prefix / 'Users/Other Guest'
        self.env['RIOT_GUEST_HOME'] = str(override)
        result = self.run_script('build/runtime/tools/install-riot-presentation-runtime.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((override / 'RuntimeLibraries/libsystem_kernel.dylib').is_file())
        self.assertFalse(self.guest.exists())

    def prepare_validation(self):
        self.configure()
        for relative in VALIDATION_INPUTS:
            path = self.guest / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'\xcf\xfa\xed\xfe' + b'\0' * 5000)
        self.stub('llvm-objdump', '''printf '%s\\n' "$*" >> "$FIXTURE_LOG"
exit "${CHECK_FAIL:-0}"''')

    def test_python_installers_use_overrides_and_repeat(self):
        self.configure()
        override_prefix = Path(self.tmp.name) / 'runtime override prefix'
        override = override_prefix / 'Users/Other Guest'
        self.env.update(DPREFIX=str(override_prefix), RIOT_GUEST_HOME=str(override))
        for name in ('libsystem_c.dylib', 'libc++.1.dylib', 'libc++abi.dylib',
                     'libsystem_platform.dylib', 'libsystem_kernel.dylib'):
            (self.root / 'build' / ('riot-' + name)).write_bytes(b'\xcf\xfa\xed\xfe fixture')
        for _ in range(2):
            result = self.run_script('build/runtime/tools/install-riot-libs-runtime.py')
            self.assertEqual(result.returncode, 0, result.stderr)
            records = json.loads(result.stdout)['libraries']
            self.assertTrue(records)
            self.assertTrue(all(str(override) in record['path'] for record in records))
        # The memory installer requires existing regular destination libraries.
        for target in (override / 'RuntimeLibraries/libsystem_kernel.dylib',
                       override_prefix / 'usr/lib/system/libsystem_kernel.dylib'):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'\xcf\xfa\xed\xfe old')
        result = self.run_script('build/runtime/tools/install-riot-memory-runtime.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((override / 'RuntimeLibraries/libsystem_kernel.dylib').read_bytes(),
                         b'\xcf\xfa\xed\xfe fixture')
        self.assertFalse(self.prefix.exists())

    def test_gpu_install_uses_custom_paths_and_repeats(self):
        self.configure()
        self.runtime_stubs()
        self.presentation_inputs()
        # All compiler outputs are inert fixture files; filesystem installs remain real.
        outputs = ('m333-IOSurface', 'm327-OpenGL', 'm336-QuartzCore', 'm341-CoreVideo',
                   'riot-CoreAudio', 'riot-AudioToolbox', 'riot-CoreGraphics', 'riot-CoreText',
                   'riot-CoreFoundation', 'riot-Metal', 'riot-CarbonCore', 'riot-libsystem_kernel.dylib',
                   'riot-libsystem_malloc.dylib', 'riot-libsystem_pthread.dylib',
                   'riot-libobjc.A.dylib', 'riot-libc++abi.dylib', 'riot-libindium.dylib', 'riot-libiridium.dylib',
                   'riot-AppKit', 'riot-X11',
                   'riot-libsystem_duct.dylib', 'riot-CoreAudioComponent',
                   'darling-src/build/src/native/libGL.dylib',
                   'darling-src/build/src/frameworks/CoreServices/src/LaunchServices/LaunchServices',
                   'darling-src/build/src/frameworks/Accelerate/vecLib/vDSP/libvDSP.dylib')
        for name in outputs:
            output = self.root / 'build' / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b'\xcf\xfa\xed\xfe fixture')
        probe = self.root / 'build/riot-host-message-check'
        probe.write_text('#!/bin/sh\nexit 0\n')
        probe.chmod(0o755)
        sdk = self.root / 'sdk'
        for name in ('IOSurface', 'OpenGL', 'CoreVideo', 'CoreAudio', 'AudioToolbox',
                     'CoreGraphics', 'CoreText', 'Metal'):
            binary = sdk / f'System/Library/Frameworks/{name}.framework/Versions/A/{name}'
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text('sdk')
            binary.chmod(0o555)
        for relative in (
            'System/Library/Frameworks/OpenGL.framework/Versions/A/Libraries/libGL.dylib',
            'System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/LaunchServices',
            'System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/CarbonCore.framework/Versions/A/CarbonCore',
            'System/Library/Frameworks/Accelerate.framework/Versions/A/Frameworks/vecLib.framework/Versions/A/libvDSP.dylib',
            'System/Library/Components/CoreAudio.component/Contents/MacOS/CoreAudio'):
            binary = sdk / relative
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text('sdk')
            binary.chmod(0o555)
        import plistlib
        plist = self.root / 'build/darling-src/src/CoreAudio/CoreAudioComponent/Info.plist'
        plist.parent.mkdir(parents=True)
        plist.write_bytes(plistlib.dumps({'AudioComponents': [{'version': 1}]}))
        for relative in ('usr/lib/system/libsystem_malloc.dylib', 'usr/lib/libobjc.A.dylib',
                         'usr/lib/libc++abi.dylib', 'usr/lib/darling/libindium.dylib',
                         'usr/lib/darling/libiridium.dylib', 'usr/lib/system/libsystem_pthread.dylib'):
            path = sdk / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('sdk library')
        result = self.run_script('build/runtime/tools/install-riot-presentation-runtime.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        for _ in range(2):
            result = self.run_script('build/runtime/tools/install-riot-gpu-runtime.sh')
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.guest / 'RuntimeLibraries/libGL.dylib').is_file())
        self.assertTrue((self.guest / 'RuntimeFrameworks/CarbonCore.framework/Versions/A/CarbonCore').is_file())
        self.assertFalse((self.home / '.darling').exists())

    def test_top_level_installer_uses_selected_destinations_and_fails_closed(self):
        real_python = sys.executable
        real_sh = shutil.which('sh')
        self.stub('python3', '''case "$1" in
 scripts/configure.py|*validate-riot-runtime.py|*check-darwin-tlv-calls.py)
  exec REAL_PYTHON "$@";;
 *ensure-darling-runtime.py|*stop-darling-runtime.py|*install-darling-system-profiler.py|*install-riot-libs-runtime.py) :;;
 *) exit 90;; esac'''.replace('REAL_PYTHON', real_python))
        self.stub('darling', ':')
        fixture_inputs = Path(self.tmp.name) / 'expected inputs'
        fixture_inputs.write_text('\n'.join(p for p in VALIDATION_INPUTS if p != 'libDarlingXShm.dylib') + '\n')
        self.env['FIXTURE_INPUTS'] = str(fixture_inputs)
        self.stub('sh', '''case "$1" in
 *install-riot-presentation-runtime.sh)
  mkdir -p "$RIOT_GUEST_HOME/RuntimeLibraries" "$RIOT_GUEST_HOME/RuntimeFrameworks/AppKit.framework/Versions/C"
  printf '\\317\\372\\355\\376fixture' > "$RIOT_GUEST_HOME/RuntimeLibraries/libsystem_kernel.dylib"
  cp "$RIOT_GUEST_HOME/RuntimeLibraries/libsystem_kernel.dylib" "$RIOT_GUEST_HOME/libDarlingXShm.dylib"
  cp "$RIOT_GUEST_HOME/libDarlingXShm.dylib" "$RIOT_GUEST_HOME/RuntimeLibraries/libc++.1.dylib"
  cp "$RIOT_GUEST_HOME/libDarlingXShm.dylib" "$RIOT_GUEST_HOME/RuntimeFrameworks/AppKit.framework/Versions/C/AppKit"
  while IFS= read -r relative; do
   mkdir -p "$(dirname "$RIOT_GUEST_HOME/$relative")"
   cp "$RIOT_GUEST_HOME/libDarlingXShm.dylib" "$RIOT_GUEST_HOME/$relative"
  done < "$FIXTURE_INPUTS"
  if [ "${MISSING_INPUT:-0}" = 1 ]; then rm "$RIOT_GUEST_HOME/RuntimeLibraries/libc++.1.dylib"; fi;;
 *install-riot-gpu-runtime.sh|*build-riot-libs-runtime.sh) :;;
 *) exit 90;; esac''')
        self.stub('llvm-objdump', '''printf '%s\\n' "$*" >> "$FIXTURE_LOG"
exit "${CHECK_FAIL:-0}"''')
        def run():
            return subprocess.run([real_sh, str(self.root / 'scripts/install-runtime.sh')],
                                  env=self.env, text=True, capture_output=True, timeout=20)
        for override in (None, self.prefix / 'Users/Other Guest'):
            if override:
                self.env['RIOT_GUEST_HOME'] = str(override)
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr)
            destination = override or self.guest
            self.assertIn(str(destination), self.log.read_text())
            self.assertEqual((self.prefix / 'private/tmp').stat().st_mode & 0o7777, 0o1777)
        self.env['CHECK_FAIL'] = '1'
        self.assertNotEqual(run().returncode, 0)
        self.env.update(CHECK_FAIL='0', MISSING_INPUT='1')
        self.assertNotEqual(run().returncode, 0)

    def test_existing_offline_launcher_check(self):
        self.configure()
        result = self.run_script('tools/riot-launcher-offline-check.py')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_paths_reject_guest_override_outside_prefix(self):
        self.configure()
        self.runtime_stubs()
        self.env['RIOT_GUEST_HOME'] = str(self.home / 'outside prefix')
        result = self.run_script('build/runtime/tools/install-riot-presentation-runtime.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists(), 'invalid destinations must fail before building/stopping')

    def test_validation_uses_host_guest_override(self):
        self.prepare_validation()
        override = self.prefix / 'Users/Override Guest'
        self.guest.rename(override)
        self.env['RIOT_GUEST_HOME'] = str(override)
        result = self.run_script('build/runtime/tools/validate-riot-runtime.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(override), self.log.read_text())

    def test_launcher_uses_same_prefix_and_guest_override(self):
        self.configure()
        override = self.prefix / 'Users/Other Guest'
        self.env['RIOT_GUEST_HOME'] = str(override)
        client = self.prefix / 'Applications/Riot Client.app/Contents/MacOS'
        client.mkdir(parents=True)
        (client / 'RiotClientServices').write_text('fixture')
        self.stub('python3', ':')
        self.stub('darling', '''printf '%s\\n%s\\n%s\\n' "$DPREFIX" "$DYLD_LIBRARY_PATH" "$DYLD_FRAMEWORK_PATH" >> "$FIXTURE_LOG"''')
        result = self.run_script('build/runtime/tools/run-riot-client.sh', '--fixture')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('/Users/Other Guest/RuntimeLibraries', self.log.read_text())
        self.assertIn(str(self.prefix), self.log.read_text())

    def test_runtime_paths_match_python_installers(self):
        self.configure()
        spec = importlib.util.spec_from_file_location('fixture_runtime_paths', self.root / 'tools/runtime_paths.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(module.runtime_paths(self.config), (self.prefix, self.guest))
        override = self.prefix / 'Users/Other Guest'
        with patch.dict(os.environ, dict(self.env, RIOT_GUEST_HOME=str(override)), clear=True):
            self.assertEqual(module.runtime_paths(self.config), (self.prefix, override))

    def test_validation_enumeration_error_fails_closed(self):
        self.prepare_validation()
        tools = self.root / 'build/runtime/tools'
        spec = importlib.util.spec_from_file_location('fixture_validator', tools / 'validate-riot-runtime.py')
        assert spec is not None and spec.loader is not None
        with patch.object(sys, 'path', [str(tools), *sys.path]):
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        def broken_walk(folder, onerror):
            onerror(PermissionError('fixture enumeration failure'))
            return iter(())
        with patch.object(module.os, 'walk', broken_walk):
            with self.assertRaisesRegex(PermissionError, 'fixture enumeration failure'):
                module.inputs(self.guest)

    def test_validation_custom_paths_and_checker_failure(self):
        self.prepare_validation()
        result = self.run_script('build/runtime/tools/validate-riot-runtime.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.guest / 'RuntimeLibraries/libc++.1.dylib'), self.log.read_text())
        self.env['CHECK_FAIL'] = '1'
        result = self.run_script('build/runtime/tools/validate-riot-runtime.py')
        self.assertNotEqual(result.returncode, 0)

    def test_validation_missing_directories_expected_inputs_and_empty_files(self):
        self.prepare_validation()
        library = self.guest / 'RuntimeLibraries/libc++.1.dylib'
        library.write_bytes(b'')
        self.assertNotEqual(self.run_script('build/runtime/tools/validate-riot-runtime.py').returncode, 0)
        library.unlink()
        self.assertNotEqual(self.run_script('build/runtime/tools/validate-riot-runtime.py').returncode, 0)
        shutil.rmtree(self.guest / 'RuntimeFrameworks')
        self.assertNotEqual(self.run_script('build/runtime/tools/validate-riot-runtime.py').returncode, 0)
        shutil.rmtree(self.guest)
        self.guest.mkdir()
        for folder in ('RuntimeLibraries', 'RuntimeFrameworks'):
            (self.guest / folder).mkdir()
        self.assertNotEqual(self.run_script('build/runtime/tools/validate-riot-runtime.py').returncode, 0)

    def test_slow_shutdown_is_verified_before_replacements(self):
        self.configure()
        self.runtime_stubs()
        self.presentation_inputs()
        self.guest.mkdir(parents=True)
        # This emulates a slow scoped stop helper, not a host process/service.
        self.stub('python3', '''case "$1" in
 *stop-darling-runtime.py) sleep 0.2; printf stopped\\n >> "$FIXTURE_LOG";;
 *) exit 90;; esac''')
        self.env['SHUTDOWN_DELAY'] = '0.1'
        result = self.run_script('build/runtime/tools/install-riot-presentation-runtime.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('stopped', self.log.read_text())

    def test_failed_stop_with_all_compile_outputs_available(self):
        self.configure()
        self.runtime_stubs()
        self.presentation_inputs()
        self.guest.mkdir(parents=True)
        self.env['RIOT_GUEST_HOME'] = str(self.guest)
        self.env.update(STOP_FAIL='1', SHUTDOWN_FAIL='1')
        result = self.run_script('build/runtime/tools/install-riot-presentation-runtime.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stop-darling-runtime.py', self.log.read_text())
        self.assertFalse((self.guest / 'libDarlingXShm.dylib').exists())

    def test_checker_rejects_empty_and_missing_inputs(self):
        for args in ((), ('missing library',)):
            with self.subTest(args=args):
                result = self.run_script('tools/check-darwin-tlv-calls.py', *args)
                self.assertNotEqual(result.returncode, 0, result.stdout)


if __name__ == '__main__':
    unittest.main()
