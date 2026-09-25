"""Unit tests for the offline comparator; these are not Resolve bug tests."""
import unittest
import numpy as np
from check_transform_echo import expected_echo, compare


class TransformHistoryOracle(unittest.TestCase):
    def test_static_transformation_applies_to_every_sample(self):
        source = {f: np.eye(12,dtype=float)*(f-30)/32 for f in range(31,63)}
        transformed = {f: np.roll(a,3,axis=1) for f,a in source.items()}
        expected = expected_echo(transformed,31,62)
        moved_echo = {f: np.roll(a,3,axis=1) for f,a in expected_echo(source,31,62).items()}
        self.assertLess(compare(moved_echo,expected)['max_error'],1e-12)
        self.assertGreater(compare(expected_echo(source,31,62),expected)['max_error'],.1)

    def test_animated_history_uses_each_samples_transform(self):
        reference = {f: np.roll(np.eye(12),(f-31)//2,axis=1) for f in range(31,43)}
        output = expected_echo(reference,31,42,hold_step=2,length=6,layers=4,strength=1)
        weights = np.array([1,.65,.65**2,.65**3]); weights /= weights.sum()
        expected = sum(w*reference[f] for w,f in zip(weights,[41,39,37,35]))
        np.testing.assert_allclose(output[42],expected)
        self.assertGreater(float(np.abs(output[42]-reference[41]).max()),.1)

    def test_trim_start_and_hold_without_history(self):
        reference = {f: np.array([float(f)]) for f in range(31,43)}
        output = expected_echo(reference,31,42)
        np.testing.assert_allclose(output[31],reference[31])
        np.testing.assert_allclose(output[32],reference[31])
        pure = expected_echo(reference,31,42,strength=0)
        self.assertEqual(float(pure[42][0]),41)

    def test_missing_frames_and_nonfinite_rejected(self):
        with self.assertRaises(ValueError): compare({31:np.array([0])},{32:np.array([0])})
        with self.assertRaises(ValueError): compare({31:np.array([np.nan])},{31:np.array([0])})


if __name__ == '__main__':
    unittest.main()
