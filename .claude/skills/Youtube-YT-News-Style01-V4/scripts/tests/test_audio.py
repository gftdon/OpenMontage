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
if __name__=='__main__':unittest.main()
