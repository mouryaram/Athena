"""
ATHENA – APScheduler Workflow Scheduler
Fires each workflow phase at the configured time (ET).
"""
import logging
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

log = logging.getLogger("athena.scheduler")
ET  = pytz.timezone("America/New_York")

_scan_cache: list = []   # shared between phases


def _run_phase(name: str, fn, *args):
    log.info(f"Scheduler firing: {name}")
    try:
        result = fn(*args)
        global _scan_cache
        if result and isinstance(result, list):
            _scan_cache = result
    except Exception as e:
        log.error(f"Scheduler error in {name}: {e}", exc_info=True)


def create_scheduler(workflow) -> BackgroundScheduler:
    """
    Create and configure the APScheduler instance.
    workflow: ATHENAWorkflow instance.
    """
    scheduler = BackgroundScheduler(timezone=ET)

    scheduler.add_job(
        lambda: _run_phase("premarket_bias",  workflow.phase_premarket_bias),
        CronTrigger.from_crontab(config.SCHEDULE["premarket_bias"], timezone=ET),
        id="premarket_bias", replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run_phase("quant_download",  workflow.phase_quant_download),
        CronTrigger.from_crontab(config.SCHEDULE["quant_download"], timezone=ET),
        id="quant_download", replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run_phase("discord_read",    workflow.phase_discord_read),
        CronTrigger.from_crontab(config.SCHEDULE["discord_read"], timezone=ET),
        id="discord_read", replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run_phase("premarket_scan",  workflow.phase_premarket_scan),
        CronTrigger.from_crontab(config.SCHEDULE["premarket_scan"], timezone=ET),
        id="premarket_scan", replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run_phase("build_watchlist", workflow.phase_build_watchlist, _scan_cache or None),
        CronTrigger.from_crontab(config.SCHEDULE["build_watchlist"], timezone=ET),
        id="build_watchlist", replace_existing=True,
    )

    # Live cycle: every 2 minutes during market hours (9:30-16:00 ET Mon-Fri)
    scheduler.add_job(
        lambda: _run_phase("live_cycle", workflow.run_live_cycle),
        CronTrigger(
            minute="*/2", hour="9-15",
            day_of_week="mon-fri", timezone=ET,
        ),
        id="live_cycle", replace_existing=True,
    )
    # Extra: 9:30 sharp
    scheduler.add_job(
        lambda: _run_phase("live_cycle_open", workflow.run_live_cycle),
        CronTrigger.from_crontab(config.SCHEDULE["market_open_loop"], timezone=ET),
        id="live_cycle_open", replace_existing=True,
    )

    scheduler.add_job(
        lambda: _run_phase("end_of_day",      workflow.phase_end_of_day),
        CronTrigger.from_crontab(config.SCHEDULE["eod_store"], timezone=ET),
        id="end_of_day", replace_existing=True,
    )

    log.info("Scheduler configured with all ATHENA workflow jobs")
    return scheduler
