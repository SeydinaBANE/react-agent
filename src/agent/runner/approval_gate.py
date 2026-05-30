from __future__ import annotations

import asyncio
from collections import defaultdict

from agent.core.exceptions import HumanApprovalRequired
from agent.core.schemas import Action
from agent.core.telemetry import APPROVAL_PENDING, get_logger

logger = get_logger(__name__)


class ApprovalGate:
    """Suspend destructive actions until a human explicitly approves them.

    One gate instance is shared across all tasks. Each task gets its own
    asyncio.Event so approval for one task doesn't unblock another.
    """

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = defaultdict(asyncio.Event)
        self._decisions: dict[str, bool] = {}

    async def check(self, task_id: str, action: Action) -> None:
        """If the action is destructive, block until approved or rejected.

        Raises HumanApprovalRequired immediately so the caller can persist
        the waiting_approval status before suspending. The caller must then
        await `wait(task_id)` to actually suspend.
        """
        if not action.is_destructive:
            return

        logger.warning(
            "approval_required",
            task_id=task_id,
            tool=action.tool,
        )
        APPROVAL_PENDING.inc()
        raise HumanApprovalRequired(task_id=task_id, tool_name=action.tool)

    async def wait(self, task_id: str) -> bool:
        """Block until the human resolves the approval. Returns True if approved."""
        await self._events[task_id].wait()
        approved = self._decisions.get(task_id, False)
        APPROVAL_PENDING.dec()
        return approved

    def resolve(self, task_id: str, *, approved: bool) -> None:
        """Called by the API when the human approves or rejects."""
        self._decisions[task_id] = approved
        self._events[task_id].set()
        logger.info("approval_resolved", task_id=task_id, approved=approved)

    def clear(self, task_id: str) -> None:
        """Clean up gate state after task completion."""
        self._events.pop(task_id, None)
        self._decisions.pop(task_id, None)
