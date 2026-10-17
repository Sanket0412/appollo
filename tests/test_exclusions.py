from pipeline.exclusions import is_excluded, load_excluded, normalize_excluded


def test_normalization_strips_legal_and_technologies():
    assert normalize_excluded("Palantir Technologies, Inc.") == "palantir"
    assert normalize_excluded("PALANTIR") == "palantir"
    assert normalize_excluded("Walmart Inc") == "walmart"
    assert normalize_excluded("Acme Corp.") == "acme"


def test_load_ignores_blanks_comments_and_missing_file(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("# comment\n\nWalmart Inc\nPalantir Technologies\n", encoding="utf-8")
    assert load_excluded(f) == {"walmart", "palantir"}
    assert load_excluded(tmp_path / "missing.txt") == set()


def test_is_excluded_matches_variants_and_not_substrings():
    excluded = {"walmart", "palantir"}
    assert is_excluded("Walmart Inc.", excluded)
    assert is_excluded("Palantir Technologies", excluded)
    assert not is_excluded("Walmart Global Tech Services", excluded)
    assert not is_excluded("Palantir Foundry Partners", excluded)
