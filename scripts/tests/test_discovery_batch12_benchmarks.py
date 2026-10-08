import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('benchmarks', ROOT/'scripts/build_discovery_batch12_benchmarks.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BenchmarkProvenanceTest(unittest.TestCase):
    def test_retrospective_cases_are_not_promoted_to_new_validation(self):
        suite = module.build()
        self.assertEqual(12, len(suite['cases']))
        pairs = [c for c in suite['cases'] if c['kind'] == 'retrospective_source_pair']
        self.assertEqual(9, len(pairs))
        rows = json.loads(module.SOURCE.read_bytes())['candidates']
        for c in pairs:
            source = rows[int(c['source_pointer'].split('/')[-1])]
            self.assertEqual(c['target_state'], source['source_state'])
            self.assertEqual(c['source_record_sha256'], module.sha(module.encoded(source)))
            self.assertFalse(c['eligible_as_unseen_test'])
            self.assertFalse(c['promote_evidence_level'])
        nb = next(c for c in pairs if c['formula'] == 'Nb6GaSb')
        self.assertGreater(nb['countercontrols_count'], 0)
        self.assertIn('AlNb6Sb', nb['acceptance_rule'])

    def test_source_authority_change_requires_reassessment(self):
        data = json.loads(module.SOURCE.read_bytes())
        row = next(c for c in data['candidates'] if c['formula'] == 'TiNb2Mo')
        row['experimental_superconductivity'] = True
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'mutated.json'; path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'authority changed'):
                module.build(path)


if __name__ == '__main__':
    unittest.main()
