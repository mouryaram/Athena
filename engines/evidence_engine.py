"""
ATHENA – Evidence-Based Learning Engine
Rule #5: Evidence beats opinions.
Measures win rate, avg R, drawdown, best/worst conditions.
Adjusts confidence ONLY after sufficient sample sizes.
ATHENA never rewrites strategy — only fine-tunes confidence weights.
"""
import logging
from datetime import datetime
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("athena.evidence")

MIN_SAMPLE_SIZE = 20    # minimum trades before evidence influences scores


class EvidenceEngine:
    """
    Reads from the evidence_rules table and returns a confidence adjustment
    for a given setup context.
    """

    def get_adjustment(
        self,
        db,
        ticker: str,
        setup_type: str,
        weekday: Optional[str] = None,
        hour: Optional[int]    = None,
        market_condition: str  = "NEUTRAL",
    ) -> float:
        """
        Returns a confidence adjustment in range [-10, +10].
        Positive = historical edge, Negative = historical weakness.
        Only activates after MIN_SAMPLE_SIZE trades per rule.
        """
        try:
            from database.models import EvidenceRule
            adjustments = []

            # Check setup type
            rule = db.query(EvidenceRule).filter_by(rule_type="setup_type", rule_value=setup_type).first()
            if rule and rule.sample_size >= MIN_SAMPLE_SIZE:
                adjustments.append(self._calc_adj(rule))

            # Check ticker
            rule = db.query(EvidenceRule).filter_by(rule_type="ticker", rule_value=ticker).first()
            if rule and rule.sample_size >= MIN_SAMPLE_SIZE:
                adjustments.append(self._calc_adj(rule))

            # Check weekday
            if weekday:
                rule = db.query(EvidenceRule).filter_by(rule_type="weekday", rule_value=weekday).first()
                if rule and rule.sample_size >= MIN_SAMPLE_SIZE:
                    adjustments.append(self._calc_adj(rule))

            # Check hour
            if hour is not None:
                rule = db.query(EvidenceRule).filter_by(rule_type="hour", rule_value=str(hour)).first()
                if rule and rule.sample_size >= MIN_SAMPLE_SIZE:
                    adjustments.append(self._calc_adj(rule))

            if not adjustments:
                return 0.0   # no evidence yet → no adjustment

            return round(sum(adjustments) / len(adjustments), 2)

        except Exception as e:
            log.warning(f"Evidence adjustment error: {e}")
            return 0.0

    def record_outcome(
        self,
        db,
        ticker: str,
        setup_type: str,
        outcome: str,    # WIN | LOSS | BREAKEVEN
        pnl_r: float,
        weekday: str,
        hour: int,
        market_condition: str = "NEUTRAL",
    ):
        """
        Update evidence rules after a trade closes.
        Called from the EOD workflow.
        """
        try:
            from database.models import EvidenceRule

            contexts = [
                ("setup_type",       setup_type),
                ("ticker",           ticker),
                ("weekday",          weekday),
                ("hour",             str(hour)),
                ("market_condition", market_condition),
            ]

            for rule_type, rule_value in contexts:
                rule = db.query(EvidenceRule).filter_by(
                    rule_type=rule_type, rule_value=rule_value
                ).first()

                if not rule:
                    rule = EvidenceRule(rule_type=rule_type, rule_value=rule_value)
                    db.add(rule)

                rule.sample_size += 1
                if outcome == "WIN":
                    rule.win_count += 1
                elif outcome == "LOSS":
                    rule.loss_count += 1

                rule.win_rate    = rule.win_count / max(rule.sample_size, 1)
                old_avg          = rule.avg_r
                n                = rule.sample_size
                rule.avg_r       = round((old_avg * (n-1) + pnl_r) / n, 3)
                rule.confidence_adj = self._calc_adj(rule) if rule.sample_size >= MIN_SAMPLE_SIZE else 0.0
                rule.last_updated = datetime.utcnow()

            db.commit()
            log.info(f"Evidence updated: {ticker} | {setup_type} | {outcome} | {pnl_r:.2f}R")

        except Exception as e:
            log.error(f"Error recording outcome: {e}")
            db.rollback()

    def get_statistics(self, db) -> dict:
        """Return full evidence statistics for the dashboard."""
        try:
            from database.models import EvidenceRule, TradeJournal
            rules = db.query(EvidenceRule).filter(EvidenceRule.sample_size > 0).all()
            journals = db.query(TradeJournal).all()

            total   = len(journals)
            wins    = sum(1 for j in journals if j.outcome and j.outcome.value == "WIN")
            losses  = sum(1 for j in journals if j.outcome and j.outcome.value == "LOSS")
            total_r = sum(j.pnl_r or 0 for j in journals)

            best_setup = max(
                (r for r in rules if r.rule_type == "setup_type" and r.sample_size >= 5),
                key=lambda r: r.avg_r, default=None
            )
            worst_setup = min(
                (r for r in rules if r.rule_type == "setup_type" and r.sample_size >= 5),
                key=lambda r: r.avg_r, default=None
            )

            return {
                "total_trades":  total,
                "wins":          wins,
                "losses":        losses,
                "win_rate":      round(wins / max(total, 1) * 100, 1),
                "total_r":       round(total_r, 2),
                "avg_r":         round(total_r / max(total, 1), 2),
                "best_setup":    best_setup.rule_value if best_setup  else "N/A",
                "worst_setup":   worst_setup.rule_value if worst_setup else "N/A",
                "rules_active":  sum(1 for r in rules if r.sample_size >= MIN_SAMPLE_SIZE),
                "rules_pending": sum(1 for r in rules if r.sample_size < MIN_SAMPLE_SIZE),
            }
        except Exception as e:
            log.error(f"Evidence stats error: {e}")
            return {}

    # ──────────────────────────────────────────────────────────────────────────
    # Private
    # ──────────────────────────────────────────────────────────────────────────

    def _calc_adj(self, rule) -> float:
        """Translate win rate + avg R into a -10 to +10 adjustment."""
        adj = 0.0
        if rule.win_rate > 0.65:
            adj += 5
        elif rule.win_rate > 0.55:
            adj += 2
        elif rule.win_rate < 0.35:
            adj -= 5
        elif rule.win_rate < 0.45:
            adj -= 2

        if rule.avg_r > 2.0:
            adj += 5
        elif rule.avg_r > 1.0:
            adj += 2
        elif rule.avg_r < 0:
            adj -= 5
        elif rule.avg_r < 0.5:
            adj -= 2

        return round(max(-10, min(10, adj)), 1)
