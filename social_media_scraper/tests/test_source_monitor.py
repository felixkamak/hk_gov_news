import sys; sys.path.insert(0, "/tmp/hkn/social_media_scraper")
from collectors.source_monitor import (
    snapshot_page, build_source_updates, extract_sections, extract_links,
)

KW = ["考試","報名","申請日期","截止","基本法","國安法","CRE","綜合招聘","境外","以外","退休年齡"]

# --- Realistic fixtures modelled on the actual CSB pages ---
HUB_V1 = """<html><body>
<h1>招聘事宜</h1>
<p><b>投考公務員職位申請人請留意：</b>新的退休年齡適用於2015年6月1日或之後聘任為公務員的新入職人員，文職職系為65歲，紀律部隊職系為60歲。</p>
<ul>
<li><a href="/tc_chi/recruit/application/330.html">申請手續</a></li>
<li><a href="/tc_chi/recruit/cre/949.html">綜合招聘考試及基本法及香港國安法測試</a></li>
</ul>
</body></html>"""

# V2: a brand-new sub-page link appears in the hub
HUB_V2 = HUB_V1.replace(
    '<li><a href="/tc_chi/recruit/cre/949.html">綜合招聘考試及基本法及香港國安法測試</a></li>',
    '<li><a href="/tc_chi/recruit/cre/949.html">綜合招聘考試及基本法及香港國安法測試</a></li>\n'
    '<li><a href="/tc_chi/recruit/cre/1500.html">2027年綜合招聘考試考期公布</a></li>'
)

CRE_V1 = """<html><body>
<h2>於香港舉行的綜合招聘考試</h2>
<p>是次綜合招聘考試暫定於2026年10月3日在香港舉行。申請期為2026年7月25日至8月7日。</p>
<h2>考試形式</h2>
<p>三張各45分鐘的選擇題試卷，分別是英文運用、中文運用和能力傾向測試。</p>
</body></html>"""

# CRE_V2: first section reworded + overseas registration added (the real 8-24 change)
CRE_V2 = """<html><body>
<h2>於香港舉行的綜合招聘考試</h2>
<p>是次綜合招聘考試擬於2026年10月3日在香港舉行。申請期已在2026年8月7日後完結。</p>
<h2>於香港以外地區舉行的綜合招聘考試</h2>
<p>亦暫定於2026年12月5日在香港以外的七個城市舉行。申請日期暫定由2026年9月12日至10月2日止。</p>
<h2>考試形式</h2>
<p>三張各45分鐘的選擇題試卷，分別是英文運用、中文運用和能力傾向測試。</p>
</body></html>"""

# Privacy page: an irrelevant boilerplate edit (should be captured but NOT relevant)
PRIV_V1 = """<html><body><h2>收集個人資料聲明</h2>
<p>本局會採取一切切實可行的步驟，確保所收集的個人資料準確無誤。</p></body></html>"""
PRIV_V2 = """<html><body><h2>收集個人資料聲明</h2>
<p>本局會採取一切合理可行的步驟，確保所收集的個人資料準確無誤及安全保存。</p></body></html>"""

def build(hub, cre, priv):
    return {
        "hub": snapshot_page(hub, "https://www.csb.gov.hk/tc_chi/recruit/7.html", capture_links=True),
        "cre": snapshot_page(cre, "cre"),
        "priv": snapshot_page(priv, "priv"),
    }

ok = True
def check(label, got, want):
    global ok
    p = got == want
    ok &= p
    print(f"[{'PASS' if p else 'FAIL'}] {label}: {got!r}" + ("" if p else f" (want {want!r})"))

# Sanity: section split
secs = extract_sections(CRE_V1)
check("CRE_V1 section count", len(secs), 2)
check("CRE_V1 first heading", secs[0]["heading"], "於香港舉行的綜合招聘考試")
check("hub link count", len(extract_links(HUB_V1, "https://www.csb.gov.hk/tc_chi/recruit/7.html")), 2)

prev = build(HUB_V1, CRE_V1, PRIV_V1)
curr = build(HUB_V2, CRE_V2, PRIV_V2)

# 1) First run (no previous) -> baseline, zero updates
first = build_source_updates({}, prev, KW)
check("first run emits nothing (baseline)", len(first), 0)

# 2) prev -> curr diff
ups = build_source_updates(prev, curr, KW)
by_type = {}
for u in ups: by_type.setdefault(u["change_type"], []).append(u)
print("\nchange types:", {k: len(v) for k,v in by_type.items()})

check("new hub page detected", any(u["change_type"]=="new_page" and "1500.html" in u["url"] for u in ups), True)
check("new hub page is relevant", all(u["is_relevant"] for u in ups if u["change_type"]=="new_page"), True)
check("CRE reworded section = modified", any(u["change_type"]=="modified" and "於香港舉行" in u["heading"] for u in ups), True)
check("CRE overseas section = added", any(u["change_type"]=="added" and "以外" in u["heading"] for u in ups), True)
check("overseas-added is relevant", any(u["change_type"]=="added" and u["is_relevant"] and "以外" in u["heading"] for u in ups), True)

priv_ups = [u for u in ups if u["heading"]=="收集個人資料聲明"]
check("privacy edit captured", len(priv_ups), 1)
check("privacy edit NOT relevant (kept quiet)", priv_ups[0]["is_relevant"], False)

relevant = [u for u in ups if u["is_relevant"]]
print("\n--- would surface to agent feed ---")
for u in relevant:
    print(f"  • [{u['change_type']}] {u['title']}")

print("\n===>", "ALL PASS ✅" if ok else "SOME FAILED ❌")
sys.exit(0 if ok else 1)
