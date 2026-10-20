import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
spec=importlib.util.spec_from_file_location("collector",Path(__file__).parents[1]/"scwiki_research_collect.py")
collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
class ResearchCollectorTest(unittest.TestCase):
    def test_candidate_is_not_published_or_certified_by_a_journal_reference(self):
        record=collector.parse_arxiv(b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"><entry><id>http://arxiv.org/abs/2610.12345v2</id><title>A paper</title><summary>Abstract</summary><arxiv:doi>10.1234/Test</arxiv:doi><arxiv:journal_ref>Journal</arxiv:journal_ref></entry></feed>''')[0]
        self.assertEqual(record["paperId"],"doi:10.1234/test")
        self.assertEqual(record["status"],"candidate-unreviewed")
        self.assertEqual(record["url"],"https://arxiv.org/abs/2610.12345v2")
    def test_source_failure_preserves_content_and_records_backoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(collector.urllib.request,"urlopen",side_effect=HTTPError("https://export.arxiv.org",429,"limited",{"Retry-After":"7200"},None)) as fetch:
                with self.assertRaises(HTTPError):collector.collect(root)
                attempt=json.loads(next(root.glob("*/attempt.json")).read_text())
                self.assertFalse(attempt["publishedContentChanged"])
                self.assertEqual(collector.collect(root)["status"],"source-backoff")
                self.assertEqual(fetch.call_count,1)
                self.assertFalse(list(root.glob("*/candidates.json")))
                self.assertFalse((root/"collect.lock").exists())
if __name__=="__main__":unittest.main()
