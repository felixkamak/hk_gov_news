"""Offline tests for the AO/EO news tracker (no network)."""

import json
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

from collectors.ao_eo_news_collector import classify_title, extract_body  # noqa: E402
from policy_archive import load_archive_items, write_weekly_archive  # noqa: E402


def test_classify_keeps_policy_and_drops_noise():
    assert "housing_land" in classify_title("立法會四題：推動北部都會區的會展業發展")
    assert "policy_legco" in classify_title("立法會四題：推動北部都會區的會展業發展")
    assert classify_title("行政長官哀悼吳康民逝世") == []
    assert classify_title("反非法勞工行動拘四人（附圖）") == []
    assert classify_title("財政司司長展開卡塔爾訪問行程（附圖／短片）") == []
    assert classify_title("皇崗口岸旅客出入境最新情況（附圖）") == []
    assert classify_title("政務司副司長在立法會人力事務委員會政策簡報會就二○二六年《施政報告》中鼓勵生育措施開場發言")


def test_extract_body_prefers_pressrelease_span():
    html = """<html><body><div id="header">導航</div>
    <span id="pressrelease">第一段內容。<br>第二段內容。</span>
    <script>var x=1;</script></body></html>"""
    body = extract_body(html)
    assert "第一段內容" in body and "第二段內容" in body
    assert "導航" not in body and "var x" not in body


def test_extract_body_falls_back_and_truncates():
    html = "<html><body><p>" + "字" * 100 + "</p></body></html>"
    assert extract_body(html, max_chars=10) == "字" * 10


def test_archive_prefix_and_prefer_new():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        old = {"url": "u1", "title": "t", "published_date": "2026-10-20", "body": "", "body_ok": False}
        new = dict(old, body="全文", body_ok=True)
        write_weekly_archive([old], out, prefix="ao_eo_news")
        write_weekly_archive([new], out, prefix="ao_eo_news", prefer_new=True)
        files = list(out.glob("ao_eo_news_*.json"))
        assert [f.name for f in files] == ["ao_eo_news_2026-W43.json"]
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data["count"] == 1 and data["items"][0]["body_ok"] is True
        assert load_archive_items(out, "ao_eo_news")["u1"]["body"] == "全文"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
