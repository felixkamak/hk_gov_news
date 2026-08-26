import sys; sys.path.insert(0, "/tmp/hkn/social_media_scraper")
from collectors.announcements_collector import AnnouncementsCollector as C

# --- Real prose from csb.gov.hk/tc_chi/recruit/cre/949.html (fetched today) ---
# Includes the earlier BLNST-deadline block as DISTRACTORS (12月5日/9月4日/12月7日)
# that must NOT be mistaken for the CRE HK sitting date.
TEXT = (
 "有意投考六個公務員職位人士請盡早報考基本法及香港國安法測試。"
 "尚未取得及格成績的申請人須另行報考數碼化測試，並在指定日期（即2026年12月5日）前取得及格成績方會獲考慮聘用。"
 "如申請人的考試日期為2026年9月4日，其暫緩考試期將由2026年9月5日起至2026年12月4日止，最快只可於2026年12月7日再次進行數碼化測試。"
 "於香港舉行的綜合招聘考試。是次綜合招聘考試擬於2026年10月3日在香港舉行。申請期已在2026年8月7日晚上11時59分（香港時間）後完結。"
 "公務員考試組將於2026年9月14日至20日期間以電郵通知申請人有關考試詳情。申請人如在2026年9月21日仍未收到上述電郵，須立即聯絡。"
 "於香港以外地區舉行的綜合招聘考試及紙本形式的基本法及香港國安法測試。"
 "為方便在香港以外地區升學或居住的考生，綜合招聘考試及紙本形式的基本法及香港國安法測試亦暫定於2026年12月5日在香港以外的七個城市舉行，"
 "包括北京、上海、倫敦、紐約、多倫多、溫哥華及悉尼。在香港以外地區舉行的考試的申請日期暫定由2026年9月12日至10月2日止。"
)

c = C.__new__(C)
c.source = {"url": "https://www.csb.gov.hk/tc_chi/recruit/cre/949.html", "name": "公務員事務局"}

def check(label, got, want):
    ok = got == want
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f"  (expected {want!r})"))
    return ok

allok = True
allok &= check("HK exam date (survives 是次/擬於)", c._extract_next_cre_exam_date(TEXT), "2026-10-03")
allok &= check("HK application closed", c._hk_application_closed(TEXT), True)
allok &= check("HK app window (overseas not mis-stitched)", c._extract_application_window(TEXT), ("", ""))
allok &= check("Overseas exam date", c._extract_overseas_exam_date(TEXT), "2026-12-05")
allok &= check("Overseas application window (9/12-10/2)", c._extract_overseas_application_window(TEXT), ("2026-09-12", "2026-10-02"))

print("\n--- emitted items ---")
hk = c._parse_hk_cre(TEXT)
ov = c._parse_overseas_cre_sitting(TEXT)
for it in hk + ov:
    print(f"  • [{it['title']}] closing={it['closing_date']!r}\n      {it['summary']}")

allok &= check("HK item count", len(hk), 1)
allok &= check("Overseas item count", len(ov), 1)
allok &= check("Overseas item is 報名 (window open today)", ov[0]['title'], "綜合招聘考試（境外場）報名")
allok &= check("Overseas closing date", ov[0]['closing_date'], "2026-10-02")
allok &= check("Overseas summary has 9/12 window", "2026-09-12" in ov[0]['summary'], True)
allok &= check("Overseas summary lists 北京/上海", ("北京" in ov[0]['summary'] and "上海" in ov[0]['summary']), True)

print("\n===>", "ALL PASS ✅" if allok else "SOME FAILED ❌")
sys.exit(0 if allok else 1)
