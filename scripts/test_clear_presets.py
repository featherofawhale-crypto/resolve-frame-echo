"""Offline regressions for preset selection and generated numeric expressions.

These checks do not load Resolve or certify native rasterization / interaction.
"""
import json
import math
import re
from types import SimpleNamespace
import unittest

from build import ROOT, CONTROLS, CONTROL_IDS, setting


def node_text(text, name):
    return re.search(rf"\b{name} = [\w.]+ \{{\nInputs = \{{\n(.*?)\n\}},\nViewInfo", text, re.S)[1]


def expr(text, name, input_id):
    body = node_text(text, name)
    return json.loads(re.search(rf'^{input_id} = Input \{{ Expression = ("(?:\\.|[^"\\])*")', body, re.M)[1])


def numeric(source, shape, enabled=1, radius=16, feather=6, width=1920, height=1080):
    # The generated preset expressions use the shared Python/Lua arithmetic
    # subset, iif(), and comp:GetPrefs(). Evaluate that subset, not arbitrary Lua.
    source = re.sub(r'comp:GetPrefs\(("[^"]+")\)', r'prefs[\1]', source)
    return eval(source, {"__builtins__": {}}, {
        "FE_Hold": SimpleNamespace(ClearShape=shape, ClearEnabled=enabled,
                                   ClearRadius=radius, ClearFeather=feather),
        "math": SimpleNamespace(min=min, max=max, sqrt=math.sqrt),
        "iif": lambda condition, yes, no: yes if condition else no,
        "prefs": {"Comp.FrameFormat.Width": width, "Comp.FrameFormat.Height": height},
    })


class ClearPresets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = setting()

    def test_choices_and_existing_ids(self):
        controls = {row[0]: row for row in CONTROLS}
        self.assertEqual(controls['ClearShape'][2:5], (0, 0, 6))
        self.assertEqual(controls['ClearShape'][5],
                         ['椭圆', '自定义钢笔', '矩形', '圆角矩形', '菱形', '横向带状', '纵向带状'])
        self.assertEqual(CONTROL_IDS['TransformEnabled'], 21)
        self.assertEqual(len(re.findall(r'\bInput\d+ = Input \{', self.text)), 25)
        self.assertIn('Input20 = InstanceInput { SourceOp = "FE_Pen", Source = "Polyline"', self.text)
        self.assertIn('Input22 = Input { Value = 0, }', self.text)
        self.assertIn('INPID_InputControl = "LabelControl", LBLC_NumInputs = 5', self.text)
        self.assertIn('LINKS_Name = "内置变换"', self.text)
        nest = self.text.index('Input22 = { INP_External = false')
        enable = self.text.index('Input21 = { LINKID_DataType = "Number"', nest)
        position = self.text.index('Input23 = { LINKID_DataType = "Point"', nest)
        self.assertLess(nest, enable)
        self.assertLess(enable, position)

    def test_internal_transform_precedes_all_temporal_sampling(self):
        transform = node_text(self.text, 'FE_Transform')
        self.assertIn('Input = Input { SourceOp = "FE_Input", Source = "Output"', transform)
        self.assertIn('Center = Input { Expression = "FrameEcho.Input23", }', transform)
        self.assertIn('Pivot = Input { Expression = "FrameEcho.Input26", }', transform)
        self.assertIn('Size = Input { Expression = "FrameEcho.Input24", }', transform)
        self.assertIn('Angle = Input { Expression = "FrameEcho.Input25", }', transform)
        self.assertIn('Blend = Input { Value = 1, }', transform)
        bypass = node_text(self.text, 'FE_TransformBypass')
        self.assertIn('Background = Input { SourceOp = "FE_Input", Source = "Output"', bypass)
        self.assertIn('Foreground = Input { SourceOp = "FE_Transform", Source = "Output"', bypass)
        self.assertIn('Mix = Input { Expression = "iif(FE_Hold.TransformEnabled>0.5,1,0)"', bypass)
        for name in ['FE_Bounds', 'FE_Hold', 'FE_Echo1', 'FE_Echo7', 'FE_BlurHold']:
            self.assertNotIn('SourceOp = "FE_Input"', node_text(self.text, name), name)
        self.assertIn('Input = Input { SourceOp = "FE_TransformBypass", Source = "Output"',
                      node_text(self.text, 'FE_Bounds'))

    def test_exclusive_masks_and_bypass(self):
        for shape in range(7):
            levels = [numeric(expr(self.text, n, 'Level'), shape)
                      for n in ['FE_Clear', 'FE_Pen', 'FE_Preset']]
            self.assertEqual(levels, [int(shape == 0), int(shape == 1), int(shape >= 2)])
            for name in ['FE_Clear', 'FE_Pen', 'FE_Preset']:
                self.assertEqual(numeric(expr(self.text, name, 'Level'), shape, enabled=0), 0)
                self.assertEqual(numeric(expr(self.text, name, 'Level'), shape, radius=0), int(name == 'FE_Pen' and shape == 1))

    def test_geometry_landscape_portrait_square(self):
        for w, h in [(1920,1080), (1080,1920), (1080,1080), (640,360)]:
            for radius in (0, 1, 16, 100):
                for shape in range(2,7):
                    args = dict(shape=shape, radius=radius, width=w, height=h)
                    width = numeric(expr(self.text, 'FE_Preset', 'Width'), **args)*w
                    height = numeric(expr(self.text, 'FE_Preset', 'Height'), **args)*h
                    angle = numeric(expr(self.text, 'FE_Preset', 'Angle'), **args)
                    corner = numeric(expr(self.text, 'FE_Preset', 'CornerRadius'), **args)
                    diameter = 2*radius/100*min(w,h)
                    self.assertGreaterEqual(width, 0)
                    self.assertGreaterEqual(height, 0)
                    self.assertEqual(angle, 45 if shape == 4 else 0)
                    self.assertEqual(corner, .35 if shape == 3 else 0)
                    if shape in (2,3):
                        self.assertAlmostEqual(width, diameter*1.5)
                        self.assertAlmostEqual(height, diameter)
                    elif shape == 4:
                        self.assertAlmostEqual(width, height)
                        self.assertAlmostEqual(width*math.sqrt(2), diameter)
                    elif shape == 5:
                        self.assertGreaterEqual(width, 3*w)
                        self.assertAlmostEqual(height, diameter)
                    elif shape == 6:
                        self.assertAlmostEqual(width, diameter)
                        self.assertGreaterEqual(height, 3*h)

    def test_shared_center_feather_and_held_image(self):
        self.assertEqual(expr(self.text, 'FE_Preset', 'Center'), 'FE_Clear.Center')
        self.assertEqual(expr(self.text, 'FE_Preset', 'SoftEdge'), expr(self.text, 'FE_Clear', 'SoftEdge'))
        body = node_text(self.text, 'FE_PresetOutput')
        for connection in ['Background = Input { SourceOp = "FE_PenOutput", Source = "Output"',
                           'Foreground = Input { SourceOp = "FE_Hold", Source = "Output"',
                           'EffectMask = Input { SourceOp = "FE_Preset", Source = "Mask"']:
            self.assertIn(connection, body)
        self.assertIn('MainOutput1 = InstanceOutput { SourceOp = "FE_PresetOutput"', self.text)

    def test_cadence_echo_and_motion_contract(self):
        """Keep the public regression suite self-contained.

        Earlier internal QA compared against a local predecessor file.  The
        open-source package instead asserts the graph contract directly, so a
        fresh clone can run the test without unreleased fixtures.
        """
        source_time = expr(self.text, 'FE_Hold', 'SourceTime')
        self.assertIn('comp.RenderStart', source_time)
        self.assertIn('comp.RenderEnd', source_time)
        for index in (1, 7):
            body = node_text(self.text, f'FE_Echo{index}')
            self.assertIn('InterpolateBetweenFrames = Input { Value = 0, }', body)
        self.assertIn('Input = Input { SourceOp = "FE_Flow", Source = "Output"',
                      node_text(self.text, 'FE_Blur'))
        self.assertIn('Type = Input { Expression = "iif(FE_Hold.MotionMode>1.5,3,0)"',
                      node_text(self.text, 'FE_Motion'))
        self.assertIn('Background = Input { SourceOp = "FE_Hold", Source = "Output"',
                      node_text(self.text, 'FE_Output'))


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ClearPresets))
    report = {'pass': result.wasSuccessful(), 'tests_run': result.testsRun,
              'scope': 'offline_numeric_expressions_and_graph_contract',
              'resolve_loaded': False, 'native_rasterization_tested': False}
    (ROOT/'validation/preset-offline-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
