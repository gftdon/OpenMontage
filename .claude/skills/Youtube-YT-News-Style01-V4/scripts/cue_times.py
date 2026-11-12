#!/usr/bin/env python3
"""Spoken times of a phrase or number, so cards can be keyed to real word times instead of typed ones.

  cue_times.py --words words_by_line.txt --script script.txt --find "13,000" [--near 195]

Prints JSON {"query", "kind", "occurrences":[{"line","start","matched"}], "nearest"?}. A purely numeric
query matches the whole number (commas / Thai digits tolerated); anything else is a case-insensitive,
whitespace-tolerant substring of the script. `start` is the start time of the word-timing token carrying
the first matched character (null if the word timing does not cover it). Exit 0 if found, 1 if not,
2 on bad input. Offline.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode_data as ed


def find(clock, query):
    q = ed.norm_digits(query.strip())
    if re.fullmatch(r'\d+(?:,\d{3})*(?:\.\d+)?%?', q):
        rx, kind = ed.number_regex(q.rstrip('%').replace(',', '')), 'number'
    else:
        rx, kind = ed.text_regex(q), 'text'
    occ = [{'line': o[3], 'start': o[2], 'matched': o[1]} for o in clock.occurrences(rx)]
    return kind, occ


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--words', required=True)
    ap.add_argument('--script', required=True)
    ap.add_argument('--find', required=True)
    ap.add_argument('--near', type=float, help='also report the occurrence nearest to this time (seconds)')
    a = ap.parse_args(argv)
    try:
        if not a.find.strip():
            raise ed.EpisodeFormatError('--find is empty')
        clock = ed.ScriptClock(ed.load_script_lines(a.script), ed.load_words(a.words))
    except (ed.EpisodeFormatError, OSError) as e:
        print(json.dumps({'error': str(e)}, ensure_ascii=False))
        return 2
    kind, occ = find(clock, a.find)
    result = {'query': a.find, 'kind': kind, 'occurrences': occ}
    if a.near is not None:
        timed = [o for o in occ if o['start'] is not None]
        if timed:
            result['nearest'] = min(timed, key=lambda o: abs(o['start'] - a.near))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if occ else 1


if __name__ == '__main__':
    sys.exit(main())
