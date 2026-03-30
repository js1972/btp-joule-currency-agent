import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    InternalError,
    InvalidParamsError,
    Part,
    TaskState,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils import (
    new_agent_text_message,
    new_task,
)
from a2a.utils.errors import ServerError

from agent import CurrencyAgent
from logging_utils import payload_logging_enabled


logger = logging.getLogger(__name__)


class CurrencyAgentExecutor(AgentExecutor):
    """Currency Conversion AgentExecutor Example."""

    def __init__(self):
        self.agent = CurrencyAgent()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        error = self._validate_request(context)
        if error:
            raise ServerError(error=InvalidParamsError())

        query = context.get_user_input()
        task = context.current_task
        
        if not task:
            task = new_task(context.message)  # type: ignore
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        logger.info(
            'Executing request for task_id=%s context_id=%s new_task=%s',
            task.id,
            task.context_id,
            context.current_task is None,
        )
        if logger.isEnabledFor(logging.DEBUG) and payload_logging_enabled():
            logger.debug('Inbound user query for task_id=%s: %r', task.id, query)

        try:
            async for item in self.agent.stream(query, task.context_id):
                is_task_complete = item['is_task_complete']
                require_user_input = item['require_user_input']
                if logger.isEnabledFor(logging.DEBUG) and payload_logging_enabled():
                    logger.debug(
                        'Agent stream item for task_id=%s: %s',
                        task.id,
                        {
                            'is_task_complete': is_task_complete,
                            'require_user_input': require_user_input,
                            'content': item['content'],
                        },
                    )

                if not is_task_complete and not require_user_input:
                    await updater.update_status(
                        TaskState.working,
                        new_agent_text_message(
                            item['content'],
                            task.context_id,
                            task.id,
                        ),
                    )
                elif require_user_input:
                    # Joule extracts the final reply from task artifacts, so
                    # user-facing failures and clarification messages must be
                    # normalized into the same artifact shape as successes.
                    await updater.add_artifact(
                        [Part(root=TextPart(text=item['content']))],
                        name='conversion_result',
                    )
                    await updater.complete()
                    break
                else:
                    await updater.add_artifact(
                        [Part(root=TextPart(text=item['content']))],
                        name='conversion_result',
                    )
                    await updater.complete()
                    break

            logger.info(
                'Completed request for task_id=%s context_id=%s',
                task.id,
                task.context_id,
            )

        except Exception:
            logger.exception(
                'Request failed for task_id=%s context_id=%s',
                task.id,
                task.context_id,
            )
            raise ServerError(error=InternalError())

    def _validate_request(self, context: RequestContext) -> bool:
        return False

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise ServerError(error=UnsupportedOperationError())
