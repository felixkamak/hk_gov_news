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
