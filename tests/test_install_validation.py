import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_install_validation as validation


class ReleaseValidationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.directory=self.root/'evidence'
        self.artifact=self.root/'release.zip';self.artifact.write_bytes(b'release fixture')
        self.baseline=self.root/'prior-release.zip';self.baseline.write_bytes(b'previous fixture')
        self.proof=self.root/'session.log';self.proof.write_text('fixture test observation')

    def record(self,case='feature.taskbar',**kwargs):
        options=dict(status='passed',origin='manual',environment='physical',distro='arch',niri_version='niri fixture',
                     tester='fixture operator',hardware='fixture GPU and displays',display_count=2,clean=True,
                     proof=[self.proof],notes='Fixture observation',baseline=self.baseline)
        options.update(kwargs)
        return validation.record(self.directory,self.artifact,case,**options)

    def reviewed(self,case,**kwargs):
        path=self.record(case,**kwargs);validation.review(path,'fixture reviewer','Checked attached log against observation');return path

    def test_no_evidence_means_not_certified(self):
        report=validation.check(self.directory,self.artifact)
        self.assertFalse(report['complete_support'])
        self.assertEqual(len(report['matrix']),17)
        self.assertTrue(all(row['status']=='pending' for row in report['matrix'].values()))

    def test_all_cases_need_separate_human_review(self):
        paths=[self.record(case) for case in validation.CASES]
        self.assertFalse(validation.check(self.directory,self.artifact)['complete_support'])
        for path in paths:validation.review(path,'fixture reviewer','Observed proof confirms scenario')
        self.assertTrue(validation.check(self.directory,self.artifact)['complete_support'])

    def test_container_vm_and_nested_cannot_promote_physical_support(self):
        for environment in ('container','vm','nested'):
            for case in validation.CASES:self.reviewed(case,environment=environment)
            self.assertFalse(validation.check(self.directory,self.artifact)['complete_support'])

    def test_nonclean_or_nonarch_evidence_cannot_grant_complete_support(self):
        for case in validation.CASES:self.reviewed(case,clean=False)
        self.assertFalse(validation.check(self.directory,self.artifact)['complete_support'])
        for case in validation.CASES:self.reviewed(case,distro='ubuntu')
        self.assertFalse(validation.check(self.directory,self.artifact)['complete_support'])

    def test_automatic_success_cannot_receive_manual_release_review(self):
        path=self.record(origin='automated')
        with self.assertRaisesRegex(ValueError,'manual'):validation.review(path,'reviewer','notes')
        self.assertFalse(validation.check(self.directory,self.artifact)['complete_support'])

    def test_changed_artifact_or_proof_invalidates_result(self):
        path=self.reviewed('feature.taskbar')
        row=json.loads(path.read_text());proof=path.parent/row['proof'][0]['file'];proof.write_text('changed')
        report=validation.check(self.directory,self.artifact)
        self.assertIn('changed proof',' '.join(report['matrix']['feature.taskbar']['latest']['errors']))
        self.artifact.write_bytes(b'different release')
        report=validation.check(self.directory,self.artifact)
        self.assertEqual(report['matrix']['feature.taskbar']['latest'],None)
        self.assertEqual(report['rejected_records'][0]['reason'],'different release artifact')

    def test_changed_observation_invalidates_review(self):
        path=self.reviewed('feature.taskbar');row=json.loads(path.read_text());row['notes']='edited after review';path.write_text(json.dumps(row))
        report=validation.check(self.directory,self.artifact)
        self.assertFalse(report['matrix']['feature.taskbar']['latest']['reviewed'])

    def test_new_failure_supersedes_old_success(self):
        self.reviewed('feature.taskbar')
        self.record('feature.taskbar',status='failed',notes='Observed later failure')
        report=validation.check(self.directory,self.artifact)
        self.assertEqual(report['matrix']['feature.taskbar']['status'],'pending')
        self.assertEqual(report['matrix']['feature.taskbar']['latest']['status'],'failed')

    def test_multimonitor_and_baseline_require_real_details(self):
        self.reviewed('state.multi_monitor',display_count=1)
        self.reviewed('install.upgrade',baseline=None)
        report=validation.check(self.directory,self.artifact)
        self.assertIn('at least two',report['matrix']['state.multi_monitor']['latest']['errors'][0])
        self.assertIn('baseline',report['matrix']['install.upgrade']['latest']['errors'][0])

    def test_no_proof_pass_and_symlink_proof_rejected(self):
        with self.assertRaises(ValueError):self.record(proof=[])
        link=self.root/'link.log';link.symlink_to(self.proof)
        with self.assertRaises(ValueError):self.record(proof=[link])

    def test_nested_missing_dependency_records_blocked_never_passed(self):
        with patch.object(validation.shutil,'which',return_value=None):
            path=validation.run_nested('tray',self.directory,self.artifact)
        row=json.loads(path.read_text())
        self.assertEqual(row['status'],'blocked');self.assertEqual(row['environment'],'nested')
        self.assertFalse(validation.check(self.directory,self.artifact)['complete_support'])

    def test_check_cli_writes_artifact_bound_report_and_nonzero_pending(self):
        with patch('builtins.print'):
            self.assertEqual(validation.main(['--check','--artifact',str(self.artifact),'--directory',str(self.directory)]),2)
        report=json.loads((self.directory/'support-report.json').read_text())
        self.assertEqual(report['artifact_sha256'],validation.digest(self.artifact))
        self.assertRegex(report['report_sha256'],'^[a-f0-9]{64}$')

if __name__=='__main__':unittest.main()
