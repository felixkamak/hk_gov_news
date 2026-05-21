"""Configuration for Hong Kong government news aggregation."""

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "collector.log"

REQUEST_TIMEOUT = 15
REQUEST_RETRIES = 3
POLITE_DELAY_SECONDS = 3
CLASSIFIER_BATCH_SIZE = 10

ANTHROPIC_MODEL = "claude-sonnet-4-20250514"

RSS_FEEDS = [
    {
        "name": "RTHK Local News",
        "source_name": "RTHK",
        "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",
    },
    {
        "name": "RTHK Finance",
        "source_name": "RTHK",
        "url": "https://rthk.hk/rthk/news/rss/c_expressnews_cfinance.xml",
    },
]

HTML_PAGES = [
    {
        "name": "All Gov Press Releases Today",
        "source_name": "香港政府新聞網",
        "url": "https://www.info.gov.hk/gia/general/ctoday.htm",
        "kind": "info_gov",
    },
    {
        "name": "IMMD Press Releases",
        "source_name": "入境事務處",
        "url": "https://www.immd.gov.hk/hkt/press/press_releases.html",
        "kind": "immd_press",
    },
    {
        "name": "CSB Homepage",
        "source_name": "公務員事務局",
        "url": "https://www.csb.gov.hk/tc_chi/index.html",
        "kind": "csb",
    },
    {
        "name": "CSB Press Releases",
        "source_name": "公務員事務局",
        "url": "https://www.csb.gov.hk/tc_chi/news/pressrelease/index.html",
        "kind": "csb",
    },
    {
        "name": "CSB CRE/BLNST Exam Schedule",
        "source_name": "公務員事務局",
        "url": "https://www.csb.gov.hk/tc_chi/recruit/cre/949.html",
        "kind": "csb",
    },
    {
        "name": "CSB Digital BLNST",
        "source_name": "公務員事務局",
        "url": "https://www.csb.gov.hk/tc_chi/recruit/2934.html",
        "kind": "csb",
    },
    {
        "name": "LegCo Civil Service Panel",
        "source_name": "立法會",
        "url": "https://www.legco.gov.hk/tc/legco-business/panels/ps/papers-and-minutes.html",
        "kind": "legco",
    },
    {
        "name": "CSB LegCo Documents",
        "source_name": "公務員事務局",
        "url": "https://www.csb.gov.hk/tc_chi/info/2546.html",
        "kind": "csb",
    },
    {
        "name": "ACO Recruitment Page",
        "source_name": "公務員事務局",
        "url": "https://www.csb.gov.hk/tc_chi/admin/grade/cs/2323.html",
        "kind": "csb",
    },
    {
        "name": "CA Recruitment Page",
        "source_name": "公務員事務局",
        "url": "https://www.csb.gov.hk/tc_chi/admin/grade/cs/2324.html",
        "kind": "csb",
    },
    {
        "name": "GGO Recruitment Centre",
        "source_name": "公務員事務局",
        "url": "https://www.csb.gov.hk/tc_chi/admin/grade/cs/2906.html",
        "kind": "csb",
    },
    {
        "name": "IMMD Career Page",
        "source_name": "入境事務處",
        "url": "https://www.immd.gov.hk/hkt/contact/career.html",
        "kind": "immd_career",
    },
]

JOB_SOURCE = {
    "name": "CSB Job Vacancy System",
    "source_name": "公務員事務局",
    "url": "https://csboa2.csb.gov.hk/csboa/jve/JVE_001_text.action?languageType=1",
}

URGENT_TITLE_KEYWORDS = [
    "招聘",
    "截止申請",
    "考試日期",
    "筆試",
    "面試通知",
    "成績公布",
    "入境事務助理員",
    "助理文書主任",
    "文書助理",
]

URGENT_JOB_KEYWORDS = [
    "入境事務助理員",
    "助理文書主任",
    "文書助理",
    "二級私人秘書",
]
