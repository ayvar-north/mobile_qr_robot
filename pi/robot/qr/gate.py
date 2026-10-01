"""Стабилизация QR, приоритет STOP и защита от повторного предъявления."""

from dataclasses import dataclass

from robot.qr.schema import QrRejected, parse
from robot.types import CardCommand, DetectionBatch


@dataclass(frozen=True)
class GateEvent:
    kind: str
    card: CardCommand | None = None


class CardGate:
    def __init__(self, max_pwm: int, max_step_ms: int):
        self.max_pwm = max_pwm
        self.max_step_ms = max_step_ms
        self.last_frame = -1
        self.last_seen_ns = None
        self.candidate = None
        self.count = 0
        self.absent_since_ns = None
        self.last_empty_ns = None
        self.need_clean = True
        self.blocked = True
        self.seen_ids = {}

    def reset_for_start(self):
        """Карточка, уже лежащая перед камерой, не должна сработать после START."""
        self.need_clean = True
        self.blocked = True
        self.absent_since_ns = None
        self.last_empty_ns = None
        self.candidate = None
        self.count = 0
        self.seen_ids.clear()

    def observe(self, batch: DetectionBatch, busy: bool, now_ns: int) -> GateEvent | None:
        if batch.frame_id <= self.last_frame or now_ns - batch.captured_at_ns > 500_000_000:
            return None
        self.last_frame = batch.frame_id
        cards = []
        for payload in batch.payloads:
            try:
                cards.append(parse(payload, self.max_pwm, self.max_step_ms))
            except QrRejected:
                continue
        # STOP проходит после одного кадра и раньше всех обычных карточек.
        if any(card.action == "stop" for card in cards):
            self.reset_for_start()
            return GateEvent("stop")
        unique = {(card.card_id, card.content_hash): card for card in cards}
        if unique:
            self.absent_since_ns = None
            self.last_empty_ns = None
        ids = {}
        for card in unique.values():
            if card.card_id in ids and ids[card.card_id] != card.content_hash:
                self.blocked = True
                self.candidate = None
                return GateEvent("id_conflict")
            ids[card.card_id] = card.content_hash
        if len(unique) > 1:
            self.blocked = True
            self.candidate = None
            return GateEvent("ambiguous")
        if not unique:
            self.candidate = None
            self.count = 0
            if (self.absent_since_ns is None or self.last_empty_ns is None or
                    batch.captured_at_ns - self.last_empty_ns > 250_000_000):
                self.absent_since_ns = batch.captured_at_ns
            self.last_empty_ns = batch.captured_at_ns
            if batch.captured_at_ns - self.absent_since_ns >= 800_000_000:
                self.need_clean = False
                self.blocked = False
            return None
        self.absent_since_ns = None
        self.last_empty_ns = None
        card = next(iter(unique.values()))
        old_hash = self.seen_ids.get(card.card_id)
        if old_hash is not None and old_hash != card.content_hash:
            self.blocked = True
            return GateEvent("id_conflict")
        self.seen_ids[card.card_id] = card.content_hash
        if busy or self.need_clean or self.blocked:
            self.candidate = None
            self.count = 0
            self.blocked = True
            return None
        identity = (card.card_id, card.content_hash)
        if identity != self.candidate or self.last_seen_ns is None or batch.captured_at_ns - self.last_seen_ns > 250_000_000:
            self.candidate = identity
            self.count = 1
        else:
            self.count += 1
        self.last_seen_ns = batch.captured_at_ns
        if self.count == 3:
            self.blocked = True
            return GateEvent("card", card)
        return None
