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
        "url": "https://csboa2.csb.gov.hk/csboa/jve/JVE_001_text.action?languageType=1",
    },
    {
        "name": "IMMD Recruitment",
        "source_name": "入境事務處",
        "url": "https://www.immd.gov.hk/hkt/recruitment",
    },
    {
        "name": "Customs Job Opportunities",
        "source_name": "香港海關",
        "url": "https://www.customs.gov.hk/tc/customs-announcement/job-opportunities/",
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
    {
        "name": "CSB CRE/BLNST on CSBOA",
        "source_name": "公務員事務局",
        "url": "https://csboa2.csb.gov.hk/csboa/",
    },
]
