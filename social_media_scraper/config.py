"""Configuration for 小紅書-focused government recruitment and exam scraping."""

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "collector.log"

POLITE_DELAY_SECONDS = 2
REQUEST_TIMEOUT = 15
REQUEST_RETRIES = 3

URGENT_KEYWORDS = [
    "入境事務助理員",
    "文員",
    "助理文書主任",
    "基本法測試",
    "BLNST",
    "截止日期",
]

JOB_SOURCES = [
    {
        "name": "CSB Job Vacancy System",
        "source_name": "公務員事務局",
        # Primary + mirrors: try in order until one yields parseable jobs.
        "url": "https://csboa1.csb.gov.hk/csboa/jve/JVE_001_text.action?languageType=1",
        "urls": [
            "https://csboa1.csb.gov.hk/csboa/jve/JVE_001_text.action?languageType=1",
            "https://csboa2.csb.gov.hk/csboa/jve/JVE_001_text.action?languageType=1",
        ],
    },
]

ANNOUNCEMENT_SOURCES = [
    {
        "name": "CSB CRE Exam Schedule",
        "source_name": "公務員事務局",
        "url": "https://www.csb.gov.hk/tc_chi/recruit/cre/949.html",
    },
    {
        "name": "CSB Digital BLNST",
        "source_name": "公務員事務局",
        "url": "https://www.csb.gov.hk/tc_chi/recruit/2934.html",
    },
]

# ---------------------------------------------------------------------------
# Source-change monitor (snapshot + diff safety net)
# ---------------------------------------------------------------------------
# Every run snapshots these pages section-by-section and diffs against the
# previous snapshot, so ANY edit surfaces even when no bespoke parser covers it.
# The hub (7.html) also has its link list captured, so a brand-new sub-page is
# detected the moment CSB adds it. Snapshot persists via a committed file.
SNAPSHOT_FILE = OUTPUT_DIR / "source_snapshots.json"

MONITOR_SOURCES = [
    # hub — link list watched for brand-new sub-pages
    {"name": "招聘事宜 (hub)", "url": "https://www.csb.gov.hk/tc_chi/recruit/7.html", "is_hub": True},
    # exam-core pages (also smart-parsed elsewhere)
    {"name": "綜合招聘考試 949", "url": "https://www.csb.gov.hk/tc_chi/recruit/cre/949.html"},
    {"name": "招聘 BLNST 1372", "url": "https://www.csb.gov.hk/tc_chi/recruit/blnst/1372.html"},
    {"name": "考試事項 335", "url": "https://www.csb.gov.hk/tc_chi/recruit/exammat/335.html"},
    {"name": "數碼化 BLNST 2934", "url": "https://www.csb.gov.hk/tc_chi/recruit/2934.html"},
    # watch-only evergreen pages (surfaced only if a change hits a keyword)
    {"name": "申請手續 330", "url": "https://www.csb.gov.hk/tc_chi/recruit/application/330.html"},
    {"name": "學歷評核 333", "url": "https://www.csb.gov.hk/tc_chi/recruit/qual/333.html"},
]

# A section change is promoted to the agent-facing feed only if it mentions one
# of these; otherwise it is captured in the snapshot but kept quiet (no noise
# from privacy-statement / boilerplate edits). New sub-pages always surface.
SOURCE_RELEVANCE_KEYWORDS = [
    "考試", "報名", "申請日期", "截止", "測試", "開考", "日期", "場次",
    "基本法", "國安法", "BLNST", "CRE", "綜合招聘", "境外", "以外",
    "數碼化", "成績", "職位", "空缺", "退休年齡",
]

# ---------------------------------------------------------------------------
# info.gov.hk policy-news collection (Option 3: 公務員 + 考試時事)
# ---------------------------------------------------------------------------

# Rolling window: every run re-scrapes the last N days of info.gov.hk press
# releases so no day is missed between Mon/Wed/Fri runs. Deduped into per-week
# archive files afterwards.
POLICY_BACKFILL_DAYS = 7

# Weekly archive location: one JSON per ISO week (policy_news_2026-W34.json).
POLICY_NEWS_DIR = OUTPUT_DIR / "policy_news"

# How many current-week policy items to surface in the main triggers JSON.
POLICY_NEWS_IN_MAIN_LIMIT = 25

# ALLOWLIST -- a headline is kept only if it contains at least one of these.
# Grouped for easy tuning; membership is a simple substring match on the title.
POLICY_ALLOW_KEYWORDS = [
    # --- 公務員 / 編制 / 薪酬 / 任命 ---
    "公務員", "公職", "公務員事務", "編制", "常額", "職系", "首長級",
    "政務主任", "政務官", "行政主任", "薪酬", "薪級", "頂薪", "增薪",
    "退休金", "公積金", "任命", "委任", "出任", "就任", "常任秘書長",
    # --- 憲制 / 國安 / 基本法 (BLNST/CRE 時事核心) ---
    "基本法", "國家安全", "國安法", "國安", "一國兩制", "愛國者",
    "憲法", "人大", "全國人大", "政協", "選舉", "政制",
    # --- 管治 / 立法 / 財政 (時事素材) ---
    "立法會", "施政報告", "財政預算", "財政司", "行政長官", "特首",
    "問責", "政策局", "諮詢文件", "條例草案",
]

# EXCLUSION -- drop even if an allow keyword matched. Recruitment is handled by
# the jobs collector; these are pure noise for the policy stream.
POLICY_EXCLUDE_KEYWORDS = [
    "招聘", "請人", "職位空缺", "招考", "聘請", "招募",
    "招聘會", "紅旗", "泳灘", "天氣報告", "空氣質素",
]

# ---------------------------------------------------------------------------
# IO / 入境事務 面試備考主題層
# ---------------------------------------------------------------------------
# Fine-grained sub-topics for Immigration Officer (IO) / Immigration Assistant
# (IA) interview prep. Each item whose title matches any keyword below is
# tagged category="immigration" with the matching `subtopic`, so IO-relevant
# policy news can be pulled out of the weekly archive fast.
#
# These keywords are ALSO merged into POLICY_ALLOW_KEYWORDS below, so that
# immigration news actually survives the allowlist gate in the first place
# (previously most of it was being dropped).
POLICY_IMMIGRATION_TOPICS = {
    # 人才政策 -- 高才通 / 優才 / 專才 / 輸入勞工 等
    "talent": [
        "高才通", "高端人才", "優才", "專才", "輸入人才", "人才清單",
        "搶人才", "人才服務", "輸入勞工", "補充勞工", "外勞", "勞工輸入",
    ],
    # 執法 / 打擊 -- 非法勞工 / 偷渡 / 免遣返聲請 等
    "enforcement": [
        "非法勞工", "非法入境", "非法勞工", "黑工", "偷渡", "蛇頭",
        "免遣返", "酷刑聲請", "免遣返聲請", "假難民", "逾期逗留",
        "打擊", "執法行動", "遣返",
    ],
    # 邊境 / 口岸 / 通關
    "border": [
        "口岸", "通關", "邊境", "出入境", "管制站", "過關", "關口",
        "自助通道", "e-道",
    ],
    # 部門 / 證件 / 服務
    "dept": [
        "入境事務處", "入境處", "入境事務", "身份證", "特區護照",
        "旅行證件", "簽證", "智方便", "單程證", "家庭團聚", "居留權",
    ],
}

# Flattened immigration keyword list (dedup, order-preserving).
POLICY_IMMIGRATION_KEYWORDS = list(
    dict.fromkeys(kw for kws in POLICY_IMMIGRATION_TOPICS.values() for kw in kws)
)

# Make sure immigration headlines pass the allowlist gate.
POLICY_ALLOW_KEYWORDS = list(
    dict.fromkeys(POLICY_ALLOW_KEYWORDS + POLICY_IMMIGRATION_KEYWORDS)
)
