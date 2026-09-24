import sys,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from model import Run,Episode,replay,guarded_order,universal_guard
from oracle import exact_order,chunk_oracle,any_deadlock,BudgetExceeded,reserve_frontier
from certificates import feasible_certificate,infeasible_certificate
from check_certificate import check,InvalidCertificate
from recovery import crash_checks

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.blocked=Episode((Run(0,2,2),Run(1,2,2)),(1,1))
        self.ordered=Episode(tuple(Run(s,l,l) for s,l in ((0,1),(1,1),(0,2),(1,2))),(1,1))
    def test_final_is_not_prefix(self):
        self.assertTrue(self.blocked.final_fits());self.assertIsNone(exact_order(self.blocked)['order'])
    def test_fifo_can_strand(self):
        self.assertEqual(guarded_order(self.ordered),[0,1]);self.assertIsNotNone(exact_order(self.ordered)['order'])
    def test_guard_sufficient_not_necessary(self):
        self.assertFalse(universal_guard(self.ordered))
        e=Episode(self.ordered.runs,(1,2));self.assertTrue(universal_guard(e));self.assertIsNone(any_deadlock(e))
    def test_chunks_do_not_free_original(self):self.assertFalse(chunk_oracle(self.blocked)[0])
    def test_frontier(self):self.assertEqual(reserve_frontier(self.blocked.runs,3),[(0,2),(2,0)])
    def test_order_certificate(self):
        order=exact_order(self.ordered)['order'];self.assertTrue(check(feasible_certificate(self.ordered,order))['valid'])
    def test_closure_certificate(self):self.assertTrue(check(infeasible_certificate(self.blocked))['valid'])
    def test_corrupt_order(self):
        c=feasible_certificate(self.ordered,[0,1,2,3])
        with self.assertRaises(InvalidCertificate):check(c)
    def test_corrupt_closure(self):
        c={'instance':feasible_certificate(self.ordered,[])['instance'],'kind':'closed-set','closed_masks':[0]}
        with self.assertRaises(InvalidCertificate):check(c)
    def test_duplicate_order(self):
        with self.assertRaises(InvalidCertificate):check(feasible_certificate(self.ordered,[0,0,2,3]))
    def test_bool_is_not_integer_size(self):
        with self.assertRaises(ValueError):Run(0,2,True)
    def test_negative_reserve(self):
        with self.assertRaises(ValueError):Episode((),(-1,0))
    def test_budget_unknown(self):
        with self.assertRaises(BudgetExceeded):exact_order(self.ordered,max_states=1)
    def test_recovery(self):
        e=self.ordered;o=exact_order(e)['order'];self.assertEqual(crash_checks(e,o)['violations'],0)
    def test_recovery_mutations(self):
        e=self.ordered;o=exact_order(e)['order']
        for m in ['early-reclaim','publish-before-flush','truncated-output','wrong-owner']:
            self.assertGreater(crash_checks(e,o,mutation=m)['violations'],0,m)
    def test_bytecount_not_device(self):
        o=exact_order(self.ordered)['order'];r=crash_checks(self.ordered,o)
        self.assertEqual((r['payload_units'],r['metadata_commits']),(6,4))
    def test_one_way_final_implies_enabled(self):
        e=Episode((Run(0,3,2),Run(0,4,1)),(0,3));self.assertTrue(universal_guard(e));self.assertIsNone(any_deadlock(e))
    def test_zero_jobs(self):self.assertEqual(exact_order(Episode((),(0,0)))['order'],())
    def test_strict_mutation_type(self):
        c=feasible_certificate(self.ordered,[0,1,2,3]);c['instance']['runs'][0]['source']=False
        with self.assertRaises(InvalidCertificate):check(c)
    def test_nonobject_instance(self):
        with self.assertRaises(InvalidCertificate):check({'instance':None})
    def test_unknown_kind(self):
        c=feasible_certificate(self.ordered,[0,3,2,1]);c['kind']='not-a-proof'
        with self.assertRaises(InvalidCertificate):check(c)
    def test_goal_in_negative_certificate(self):
        c=infeasible_certificate(self.blocked);c['closed_masks'].append(3)
        with self.assertRaises(InvalidCertificate):check(c)
    def test_bool_mask(self):
        c=infeasible_certificate(self.blocked);c['closed_masks']=[False]
        with self.assertRaises(InvalidCertificate):check(c)
    def test_final_deficit_certificate(self):
        e=Episode((Run(0,3,3),),(0,0));self.assertEqual(check(infeasible_certificate(e))['kind'],'final-deficit')

if __name__=='__main__':unittest.main()
