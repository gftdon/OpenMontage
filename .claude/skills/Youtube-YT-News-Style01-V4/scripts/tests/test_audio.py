import importlib.util
from pathlib import Path
import unittest

P=Path(__file__).resolve().parents[1]/'measure_loudness.py'
class AudioTests(unittest.TestCase):
    def module(self):
        s=importlib.util.spec_from_file_location('measure_loudness',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
    def test_parser_rejects_missing_nonfinite_and_no_audio(self):
        for text in ['', '{}', '{"input_i":"-inf","input_tp":"-1","input_lra":"2","input_thresh":"-24","target_offset":"0"}']:
            with self.assertRaises(ValueError):self.module().parse_loudnorm(text)
    def test_parser_extracts_last_json(self):
        d=self.module().parse_loudnorm('log\n{"input_i":"-14.1","input_tp":"-1.2","input_lra":"2","input_thresh":"-24","target_offset":"0"}')
        self.assertEqual(-14.1,d['input_i'])
    def test_measurement_normalization_mode_not_delivered_mode(self):
        d=self.module().measurement_metrics({'input_i':-14,'input_tp':-2,'normalization_type':'dynamic'})
        self.assertNotIn('normalization_type',d)
        self.assertEqual('dynamic',d['analysis_filter_mode'])

    def test_final_acceptance_measured_not_target(self):
        m=self.module()
        for i,tp,ok in [(-14,-1,True),(-14.5,-1.1,True),(-13.5,-1.1,True),(-14.51,-1.1,False),(-14,-.99,False),(float('nan'),-2,False)]:
            self.assertEqual(ok,m.acceptance({'input_i':i,'input_tp':tp}))

    def run_cli(self, args, env=None):
        import subprocess, sys, tempfile
        d = Path(tempfile.mkdtemp(prefix='loud-'))
        self.addCleanup(__import__('shutil').rmtree, d, True)
        r = subprocess.run([sys.executable, '-B', str(P), *args, '--report', str(d / 'r.json')], capture_output=True, text=True, env=env)
        return r.returncode, d

    def test_exit_codes_missing_ffmpeg_is_4_unreadable_or_no_audio_is_2(self):
        import os, shutil, subprocess, tempfile
        if not shutil.which('ffmpeg'):
            self.skipTest('ffmpeg required')
        d = Path(tempfile.mkdtemp(prefix='loud-'))
        self.addCleanup(shutil.rmtree, d, True)
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=64x64:r=25:d=1', '-pix_fmt', 'yuv420p', str(d / 'noaudio.mp4')], check=True)
        code, _ = self.run_cli([str(d / 'noaudio.mp4')])
        self.assertEqual(2, code)
        code, _ = self.run_cli([str(d / 'does-not-exist.mp4')])
        self.assertEqual(2, code)
        (d / 'junk.mp4').write_bytes(b'not a video')
        code, _ = self.run_cli([str(d / 'junk.mp4')])
        self.assertEqual(2, code)
        env = dict(os.environ, PATH=str(d))      # no ffmpeg on PATH
        code, out = self.run_cli([str(d / 'noaudio.mp4')], env=env)
        self.assertEqual(4, code)
        self.assertIn('ffmpeg not found', (out / 'r.json').read_text())

    def test_silent_audio_is_still_a_quality_failure(self):
        import shutil, subprocess, tempfile
        if not shutil.which('ffmpeg'):
            self.skipTest('ffmpeg required')
        d = Path(tempfile.mkdtemp(prefix='loud-'))
        self.addCleanup(shutil.rmtree, d, True)
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono', '-t', '2', str(d / 'silent.wav')], check=True)
        code, _ = self.run_cli([str(d / 'silent.wav')])
        self.assertEqual(1, code)


if __name__=='__main__':unittest.main()
