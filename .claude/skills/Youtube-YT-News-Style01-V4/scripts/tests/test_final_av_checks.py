import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'final_av_checks.py'
HAVE_FFMPEG = shutil.which('ffmpeg') is not None


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *args], check=True)


@unittest.skipUnless(HAVE_FFMPEG, 'ffmpeg required')
class FinalAvTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='final-av-'))
        t = cls.tmp
        src = 'testsrc2=s=320x240:r=25:d=%s'
        ffmpeg('-f', 'lavfi', '-i', src % 4, '-pix_fmt', 'yuv420p', str(t / 'normal.mp4'))
        # 3 s frozen segment in the middle (1 s of motion, 3 s clone, 2 s of motion)
        ffmpeg('-f', 'lavfi', '-i', src % 1, '-f', 'lavfi', '-i', src % 2, '-filter_complex',
               '[0:v]tpad=stop_mode=clone:stop_duration=3[a];[a][1:v]concat=n=2:v=1:a=0', '-pix_fmt', 'yuv420p',
               str(t / 'freeze.mp4'))
        # 1 s black in the middle
        ffmpeg('-f', 'lavfi', '-i', src % 3, '-f', 'lavfi', '-i', 'color=c=black:s=320x240:r=25:d=1',
               '-f', 'lavfi', '-i', src % 2, '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0',
               '-pix_fmt', 'yuv420p', str(t / 'black.mp4'))
        # 1 s black at the very end (outro fade-out allowance)
        ffmpeg('-f', 'lavfi', '-i', src % 3, '-f', 'lavfi', '-i', 'color=c=black:s=320x240:r=25:d=1',
               '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0', '-pix_fmt', 'yuv420p', str(t / 'black_tail.mp4'))
        # frozen until the end of the file
        ffmpeg('-f', 'lavfi', '-i', src % 1, '-vf', 'tpad=stop_mode=clone:stop_duration=3', '-pix_fmt', 'yuv420p',
               str(t / 'freeze_tail.mp4'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_check(self, name, *extra, env=None):
        report = self.tmp / (name + '.report.json')
        if report.exists():
            report.unlink()
        r = subprocess.run([sys.executable, str(SCRIPT), str(self.tmp / (name + '.mp4')), '--report', str(report), *extra],
                           capture_output=True, text=True, env=env)
        return r.returncode, json.loads(report.read_text()) if report.exists() else None

    def codes(self, report):
        return sorted({i['code'] for i in report['issues']})

    def test_normal_clip_passes(self):
        code, rep = self.run_check('normal')
        self.assertEqual(0, code)
        self.assertTrue(rep['pass'])
        self.assertEqual([], rep['issues'])
        self.assertEqual('yt-news-v4-final-av', rep['schema'])
        self.assertAlmostEqual(4.0, rep['duration'], delta=0.2)
        (path, digest), = rep['inputs'].items()
        self.assertTrue(path.endswith('normal.mp4'))
        self.assertEqual(64, len(digest))

    def test_frozen_segment_is_flagged(self):
        code, rep = self.run_check('freeze')
        self.assertEqual(1, code)
        self.assertFalse(rep['pass'])
        self.assertEqual(['freeze'], self.codes(rep))
        self.assertGreaterEqual(rep['issues'][0]['duration'], 2.9)

    def test_freeze_below_threshold_is_not_flagged(self):
        code, rep = self.run_check('freeze', '--freeze-min', '3.5')
        self.assertEqual(0, code, rep)

    def test_black_segment_is_flagged(self):
        code, rep = self.run_check('black')
        self.assertEqual(1, code)
        self.assertEqual(['black'], self.codes(rep))

    def test_black_tail_allowance(self):
        code, rep = self.run_check('black_tail')
        self.assertEqual(1, code)
        code, rep = self.run_check('black_tail', '--allow-tail', '1.5')
        self.assertEqual(0, code, rep)
        # tail allowance must not hide a span that starts before the tail
        code, rep = self.run_check('black', '--allow-tail', '1.0')
        self.assertEqual(1, code)

    def test_freeze_running_to_end_of_file(self):
        code, rep = self.run_check('freeze_tail')
        self.assertEqual(1, code)
        self.assertEqual(['freeze'], self.codes(rep))
        code, rep = self.run_check('freeze_tail', '--allow-tail', '4')
        self.assertEqual(0, code, rep)

    def test_missing_input_is_bad_input_and_report_written(self):
        report = self.tmp / 'missing.report.json'
        r = subprocess.run([sys.executable, str(SCRIPT), str(self.tmp / 'nope.mp4'), '--report', str(report)],
                           capture_output=True, text=True)
        self.assertEqual(2, r.returncode)
        self.assertFalse(json.loads(report.read_text())['pass'])

    def test_not_a_video_is_bad_input(self):
        (self.tmp / 'junk.mp4').write_text('not a video')
        code, rep = self.run_check('junk')
        self.assertEqual(2, code)
        self.assertFalse(rep['pass'])

    def test_ffmpeg_missing_is_exit_4(self):
        code, rep = self.run_check('normal', env={'PATH': '/nonexistent'})
        self.assertEqual(4, code)
        self.assertFalse(rep['pass'])


if __name__ == '__main__':
    unittest.main()
