import io

from vrdb.progress import Progress, human


def test_human_scales_units():
    assert human(950) == "950"
    assert human(1500) == "2K"
    assert human(2_500_000) == "2M"


def test_update_prints_only_on_tick_boundary():
    out = io.StringIO()
    clock = iter([0.0, 1.0, 2.0, 3.0]).__next__
    p = Progress("voters", total_bytes=1000, tick=100, stream=out, clock=clock)
    p.update(rows=50, bytes_read=100)
    assert out.getvalue() == ""
    p.update(rows=100, bytes_read=500)
    assert "rows=100" in out.getvalue()


def test_update_reports_percent_and_eta():
    out = io.StringIO()
    clock = iter([0.0, 10.0, 20.0]).__next__
    p = Progress("voters", total_bytes=1000, tick=100, stream=out, clock=clock)
    p.update(rows=100, bytes_read=250)
    line = out.getvalue()
    assert "25.0%" in line
    # 10s consumed 25%, so ~30s remain
    assert "ETA 00:00:30" in line


def test_unknown_total_bytes_omits_percent_and_eta():
    out = io.StringIO()
    clock = iter([0.0, 1.0, 2.0]).__next__
    p = Progress("voters", total_bytes=None, tick=100, stream=out, clock=clock)
    p.update(rows=100, bytes_read=0)
    line = out.getvalue()
    assert "%" not in line
    assert "ETA" not in line


def test_finish_reports_total_and_rate():
    out = io.StringIO()
    clock = iter([0.0, 4.0]).__next__
    p = Progress("voters", total_bytes=1000, tick=100, stream=out, clock=clock)
    p.finish(rows=2000)
    line = out.getvalue()
    assert "2,000" in line
    assert "500" in line  # 2000 rows / 4s
