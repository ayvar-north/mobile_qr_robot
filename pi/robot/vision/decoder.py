"""OpenCV декодирует все QR в кадре, не зная о режимах робота."""

import time

from robot.types import DetectionBatch, Frame


class QrDecoder:
    def __init__(self):
        import cv2
        self.detector = cv2.QRCodeDetector()

    def decode(self, frame: Frame) -> DetectionBatch:
        try:
            ok, decoded, _, _ = self.detector.detectAndDecodeMulti(frame.image)
        except Exception as exc:
            raise RuntimeError("сбой декодера QR") from exc
        payloads = tuple(value for value in decoded if value) if ok else ()
        return DetectionBatch(frame.frame_id, frame.captured_at_ns, time.monotonic_ns(), payloads)
