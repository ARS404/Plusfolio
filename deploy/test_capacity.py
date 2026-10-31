"""Checks for report arithmetic, including restarted cgroup counter identities."""
import json
from pathlib import Path
import tempfile
import unittest
from check_capacity import summary,summarize_resources


class CapacityReportTests(unittest.TestCase):
    def test_cache_cleanup_cannot_select_release_or_neighboring_repositories(self):
        rules=json.loads((Path(__file__).parent/'yandex/registry-cache-policy.example.json').read_text())
        for rule in rules:
            prefix=rule['path_prefix']
            self.assertTrue('/build-cache/web'.startswith(prefix))
            self.assertFalse('/plusfolio/app'.startswith(prefix))
            self.assertFalse('/build-cache-neighbor/app'.startswith(prefix))

    def test_percentile_keeps_failures_and_semantic_fallback_visible(self):
        rows=[{'name':'search','ms':n,'status':200 if n<20 else 503,'bytes':10,
               'semantic':n%2==0,'pending':0} for n in range(1,21)]
        result=summary(rows)['search']
        self.assertEqual((result['p50_ms'],result['p95_ms'],result['errors']),(10.5,19,1))
        self.assertEqual((result['semantic'],result['requests']),(10,20))
        self.assertEqual(result['statuses'],{'200':19,'503':1})

    def test_restarted_containers_do_not_create_negative_cpu_or_sum_nonconcurrent_peaks(self):
        def sample(identity,cpu,memory):
            return {'phase':'update','host':{'total':1000,'available':500,'used':500,'oom_kill':0,'swap_used':0},
                'parent_cpu':{'throttled_usec':0},'services':{'web':{'id':identity,'memory':memory,'working_set':memory,
                'peak':100,'events':{'oom_kill':0},'cpu':{'usage_usec':cpu,'throttled_usec':0,'nr_throttled':0,'nr_periods':10}}}}
        rows=[sample('old',1000000,90),sample('old',2000000,70),sample('new',10000,80),sample('new',510000,75)]
        for index,row in enumerate(rows):row['at']=index
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'samples.jsonl';path.write_text('\n'.join(map(json.dumps,rows)))
            result=summarize_resources(path)['update']
        self.assertEqual(result['services']['web']['cpu_seconds'],1.5)
        self.assertEqual(result['stack_working_set_peak_bytes'],90)
        self.assertEqual(result['services']['web']['lifetime_charged_peak_bytes'],100)
        self.assertEqual(result['host_oom_kills'],0)


if __name__=='__main__':unittest.main()
