import numpy as np

from pipeline.score.embed import Candidate, Scored, job_text, select_shortlist


def _s(id_, sim, nyc=False):
    return Scored(Candidate(id_, "t", "c", None, nyc), np.zeros(384, dtype=np.float32), sim)


def test_threshold_filters():
    assert select_shortlist([_s("a", 0.6), _s("b", 0.5)], 0.55, 10) == {"a"}


def test_threshold_is_inclusive():
    assert select_shortlist([_s("a", 0.55)], 0.55, 10) == {"a"}


def test_cap_prefers_nyc_then_similarity():
    scored = [_s("hi_remote", 0.9), _s("lo_nyc", 0.6, nyc=True), _s("mid_remote", 0.7)]
    assert select_shortlist(scored, 0.55, 2) == {"lo_nyc", "hi_remote"}


def test_job_text_truncates_description():
    text = job_text("Data Scientist", "Acme", "x" * 5000)
    assert text == "Data Scientist\nAcme\n" + "x" * 2000


def test_job_text_handles_missing_description():
    assert job_text("T", "C", None) == "T\nC\n"
