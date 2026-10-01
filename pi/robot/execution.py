"""Последовательное исполнение плана: одновременно только один MOVE."""

import asyncio
import time

from robot.transport.serial_client import LinkFault
from robot.types import MotionPlan


class PlanExecutor:
    def __init__(self, link, on_finish):
        self.link = link
        self.on_finish = on_finish
        self.plan: MotionPlan | None = None
        self.step_index: int | None = None
        self.cmd_id: int | None = None
        self.task = None
        self.generation = 0

    def submit(self, plan: MotionPlan):
        if self.task is not None and not self.task.done():
            raise ValueError("BUSY")
        self.generation += 1
        self.plan = plan
        self.step_index = None
        self.cmd_id = None
        generation = self.generation
        self.task = asyncio.create_task(self._run(plan, generation))

    async def _run(self, plan: MotionPlan, generation: int):
        deadline = time.monotonic() + (plan.total_duration_ms + len(plan.steps) * 1000) / 1000
        try:
            for index, step in enumerate(plan.steps):
                if generation != self.generation or time.monotonic() >= deadline:
                    raise LinkFault("маршрут отменён или превысил срок")
                self.step_index = index
                # ID фиксируется до отправки; serial_client не меняет его при повторе.
                self.cmd_id = self.link.seq + 1
                await self.link.move(step.left_pwm_pct, step.right_pwm_pct, step.duration_ms)
            if generation == self.generation:
                self.on_finish(None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if generation == self.generation:
                self.on_finish(str(exc))
        finally:
            if generation == self.generation:
                self.plan = None
                self.step_index = None
                self.cmd_id = None

    async def cancel(self):
        self.generation += 1
        task = self.task
        self.plan = None
        self.step_index = None
        self.cmd_id = None
        self.task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def snapshot(self):
        return self.plan, self.step_index, self.cmd_id
