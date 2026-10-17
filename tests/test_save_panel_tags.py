"""Offline build/registration regressions; never invokes Darling or a compiler."""
import ast
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROBE = 'riot-save-panel-tag-check'


class SavePanelTagTests(unittest.TestCase):
    def test_only_documented_tag_selectors_are_implemented(self):
        source = (ROOT / 'tools/riot-save-panel-compat.m').read_text()
        for selector in ('setShowsTagField:', 'showsTagField', 'setTagNames:', 'tagNames'):
            self.assertIn(selector, source)
        self.assertNotIn('setShowsTags:', source)
        self.assertNotIn('showsTags', source)

    def test_builder_compiles_and_links_probe_without_embedding_shim(self):
        source = ROOT / 'tools/build-riot-appkit-runtime.py'
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            driver = project / 'tools' / source.name
            driver.parent.mkdir()
            driver.write_text(source.read_text())
            framework = project / 'build/darling-src/build/src/external/cocotron/AppKit'
            cmake = framework / 'CMakeFiles/AppKit.dir'
            cmake.mkdir(parents=True)
            (cmake / 'flags.make').write_text('C_DEFINES = -DTEST\nC_INCLUDES = -Itest\nC_FLAGS = -O0\n')
            objects = ['NSResponder', 'NSApplication', 'NSWindow', 'NSDisplay',
                       'NSView', 'NSThemeFrame', 'NSTextInput', 'NSBitmapImageRep',
                       'NSEvent.subproj/NSEvent_mouse']
            (cmake / 'link.txt').write_text('clang -o AppKit ' + ' '.join(
                f'CMakeFiles/AppKit.dir/{name}.m.o' for name in objects))
            calls = []
            with patch('subprocess.run', side_effect=lambda argv, **kw: calls.append((argv, kw))):
                runpy.run_path(str(driver), run_name='__main__')
            compiles = [argv for argv, _ in calls if str(project / f'tools/{PROBE}.m') in argv]
            self.assertEqual(len(compiles), 1, 'new probe must be built with existing AppKit probes')
            self.assertEqual(compiles[0][compiles[0].index('-o') + 1], str(project / f'build/{PROBE}.o'))
            links = [argv for argv, _ in calls if str(project / f'build/{PROBE}') in argv]
            self.assertEqual(len(links), 1)
            self.assertIn(str(project / f'build/{PROBE}.o'), links[0])
            self.assertIn('AppKit', links[0])
            compat = str(project / 'build/riot-save-panel-compat.o')
            self.assertNotIn(compat, links[0], 'probe must exercise AppKit, not its own copy of the shim')
            appkit_links = [argv for argv, kw in calls if kw.get('cwd') == framework]
            self.assertEqual(len(appkit_links), 1)
            self.assertIn(compat, appkit_links[0])

    def test_probe_registered_with_native_runner(self):
        tree = ast.parse((ROOT / 'tools/run-riot-native-check.py').read_text())
        checks = next(ast.literal_eval(node.value) for node in tree.body
                      if isinstance(node, ast.Assign) and any(
                          isinstance(target, ast.Name) and target.id == 'checks'
                          for target in node.targets))
        self.assertEqual(checks.get(PROBE), 'SAVE_PANEL_TAG_CHECK')


if __name__ == '__main__':
    unittest.main()
