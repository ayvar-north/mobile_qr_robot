"""USB-камера: каждый кадр получает монотонную метку сразу после read()."""

import time

from robot.types import Frame


class CameraFault(RuntimeError):
    """Камера не дала новый кадр."""


class CameraCapture:
    def __init__(self, path: str, width: int, height: int, fps: int):
        self.path, self.width, self.height, self.fps = path, width, height, fps
        self.device = None
        self.frame_id = 0

    def open(self):
        import cv2
        self.device = cv2.VideoCapture(self.path, cv2.CAP_V4L2)
        if not self.device.isOpened():
            raise CameraFault("камера не открылась")
        self.device.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.device.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.device.set(cv2.CAP_PROP_FPS, self.fps)
        self.device.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def read(self) -> Frame:
        if self.device is None:
            raise CameraFault("камера закрыта")
        ok, image = self.device.read()
        captured_at = time.monotonic_ns()
        if not ok:
            raise CameraFault("ошибка получения кадра")
        self.frame_id += 1
        return Frame(self.frame_id, captured_at, image)

    def close(self):
        if self.device is not None:
            self.device.release()
            self.device = None
