# -*- coding: utf-8 -*-
import sys; sys.path.insert(0,"/tmp/hkn/social_media_scraper")
from collectors.announcements_collector import AnnouncementsCollector as C

HTML_949 = """<html><body>
<h2>於香港舉行的綜合招聘考試</h2>
<p>是次綜合招聘考試擬於<strong>2026年10月3日</strong>在香港舉行。申請期已在2026年8月7日晚上11時59分（香港時間）後完結。</p>
<p>公務員考試組將於2026年9月14日至20日期間以電郵通知申請人。申請人如在<strong>2026年9月21日</strong>仍未收到上述電郵，須立即聯絡。</p>
<h2>於香港以外地區舉行的綜合招聘考試及紙本形式的「基本法及香港國安法測試」</h2>
<p>為方便在香港以外地區升學或居住的考生，綜合招聘考試亦暫定於<strong>2026年12月5日</strong>在香港以外的七個城市舉行，包括北京、上海、倫敦、紐約、多倫多、溫哥華及悉尼。在香港以外地區舉行的考試的申請日期<strong>暫定由2026年9月12日至10月2日止</strong>。</p>
</body></html>"""

class FakeResp:
    def __init__(s,h): s.content=h.encode("utf-8"); s.apparent_encoding="utf-8"; s.text=h; s.encoding="utf-8"
    def raise_for_status(s): pass

src={"url":"https://www.csb.gov.hk/tc_chi/recruit/cre/949.html","name":"CRE","source_name":"公務員事務局"}
c=C(src)
c.fetch=lambda url=None: FakeResp(HTML_949)   # bypass network, exercise full parse()->_dedupe

items=c.parse()
titles=[i["title"] for i in items]
print("parse() returned", len(items), "items:")
for i in items: print("   •", i["title"], "|", i["summary"][:60])

ok = (len(items)==2
      and "綜合招聘考試（下一輪）" in titles
      and "綜合招聘考試（境外場）報名" in titles)
print("\n===>", "PASS ✅ (both HK + overseas survive _dedupe)" if ok else "FAIL ❌")
sys.exit(0 if ok else 1)
