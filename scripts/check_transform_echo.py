"""Compare linear EXR QA renders without connecting to Resolve.

The reference must contain every frame AFTER Edit sizing, with Frame Echo
disabled. The effect render must use every-N-frame hold, echo mode, no spatial
blur and no clear-region protection. Matching values are supplied on the CLI.
This validates history pixels, not merely that the final image moved.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np


def expected_echo(reference, start, end, hold_step=2, length=6, layers=4, strength=.5):
    if hold_step < 1 or layers not in (2, 4, 8) or length < 0 or not 0 <= strength <= 1:
        raise ValueError('Invalid echo parameters')
    weights = np.array([.65**i for i in range(layers)])
    weights /= weights.sum()
    output = {}
    for frame in range(start, end+1):
        held = start + (frame-start)//hold_step*hold_step
        samples = [max(start, held-math.floor(length*i/(layers-1)+.5)) for i in range(layers)]
        history = sum(w*reference[sample] for w, sample in zip(weights, samples))
        output[frame] = (1-strength)*reference[held] + strength*history
    return output


def compare(actual, expected):
    if set(actual) != set(expected):
        raise ValueError('Frame ranges differ')
    records = []
    for frame in sorted(expected):
        a, b = actual[frame], expected[frame]
        if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
            raise ValueError(f'Invalid image at frame {frame}')
        error = np.abs(a-b)
        records.append({'frame': frame, 'max_error': float(error.max()), 'mean_error': float(error.mean())})
    return {'max_error': max(r['max_error'] for r in records), 'frames': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--effect', type=Path, required=True)
    parser.add_argument('--other-order', type=Path, help='Same final parameters, opposite order of applying effect/edit sizing')
    parser.add_argument('--start', type=int, default=31)
    parser.add_argument('--end', type=int, default=62)
    parser.add_argument('--width', type=int, default=640)
    parser.add_argument('--height', type=int, default=360)
    parser.add_argument('--hold-step', type=int, default=2)
    parser.add_argument('--length', type=float, default=6)
    parser.add_argument('--layers', type=int, choices=(2,4,8), default=4)
    parser.add_argument('--strength', type=float, default=.5)
    parser.add_argument('--tolerance', type=float, default=.002)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.start > args.end or min(args.width,args.height) <= 0 or args.tolerance < 0:
        parser.error('Invalid range, image size or tolerance')
    # Importing pixels does not invoke connect() or access a running Resolve.
    from validate_live import pixels

    def read(folder):
        return {f: pixels(folder/f'frame{f:04}.exr',args.width,args.height)
                for f in range(args.start,args.end+1)}

    reference, actual = read(args.reference), read(args.effect)
    expected = expected_echo(reference,args.start,args.end,args.hold_step,args.length,args.layers,args.strength)
    report = {'scope':'rendered_transformed_history', 'resolve_connected':False,
              'expected_echo':compare(actual,expected),
              'inputs':{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}}
    if args.other_order:
        report['operation_order'] = compare(actual,read(args.other_order))
    report['pass'] = all(report[k]['max_error'] <= args.tolerance
                         for k in ('expected_echo','operation_order') if k in report)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('expected_echo','operation_order','inputs')},ensure_ascii=False))
    raise SystemExit(0 if report['pass'] else 1)


if __name__ == '__main__':
    main()
