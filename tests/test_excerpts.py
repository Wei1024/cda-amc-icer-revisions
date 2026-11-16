from icer_revisions.excerpts import excerpt

FILLER = "lorem ipsum dolor sit amet " * 200  # ~5,400 characters with no cues


def test_priority_passages_survive_the_size_cap():
    dense = " ".join(f"The ICER was ${50_000 + i:,} per QALY with a 4{i % 10}% price reduction." for i in range(5))
    stepwise = "Table 4: CDA-AMC stepwise reanalysis. Step 1 corrected utilities, ICER $91,000 per QALY."
    text = FILLER.join([dense] * 6 + [stepwise]) + FILLER
    out = excerpt(text, max_chars=1_000)
    assert "stepwise reanalysis" in out
    assert out.count("[...]") < 6  # the cap dropped some of the dense passages


def test_table_of_contents_lines_are_dropped():
    text = "Cost-effectiveness ........ 12 " + FILLER + "The sponsor's base-case ICER was $120,000 per QALY."
    out = excerpt(text)
    assert "........" not in out
    assert "$120,000 per QALY" in out
