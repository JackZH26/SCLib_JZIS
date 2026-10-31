import pytest
from materials_ner_tc_round import provider_round


def test_extraction_and_audit_rounds_cannot_overlap_and_release_after_failure(tmp_path):
    with pytest.raises(RuntimeError):
        with provider_round(tmp_path):
            with pytest.raises(ValueError,match='already_running'):
                with provider_round(tmp_path):raise AssertionError('Second provider round entered')
            raise RuntimeError('Simulated interruption')
    with provider_round(tmp_path):pass
