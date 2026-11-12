#!/usr/bin/env python3
"""Explicit offline recovery1. Default preview; --apply is a Main-owned action."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from broll_costs import Budget,apply_recovery,apply_recovery2,config_sha256,bytes_sha256
from media_manifest import save_json

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--project',required=True);ap.add_argument('--approval',required=True);ap.add_argument('--recovery',required=True);ap.add_argument('--out',required=True);ap.add_argument('--evidence',help='required safe summary for Lead-recovery-2');ap.add_argument('--apply',action='store_true');a=ap.parse_args()
 approval=json.loads(Path(a.approval).read_text());recovery=json.loads(Path(a.recovery).read_text());b=Budget(a.project,approval)
 if not a.apply:
  save_json(a.out,{'status':'preview_only_not_applied','new_config_sha256':config_sha256(),'journal_snapshot_sha256':bytes_sha256(b.path.read_bytes()),'recovery':recovery});return
 if recovery.get('id')=='Lead-recovery-2':
  if not a.evidence:ap.error('recovery2 requires --evidence')
  result=apply_recovery2(b,recovery,a.evidence)
 else:result=apply_recovery(b,recovery)
 save_json(a.out,{'status':recovery.get('id','unknown')+'_applied','recovery_events':result['recovery_events'],'retained_attempt_ids':[e['id'] for e in result['attempts']],'retained_reserved_usd':sum(e['reserved_usd'] for e in result['attempts'])})
if __name__=='__main__':main()
