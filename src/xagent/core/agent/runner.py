import logging
import traceback
from typing import Any, Optional

from .agent import Agent
from .context import AgentContext
from .exceptions import AgentException
from .precondition import PreconditionResolver

logger = logging.getLogger(__name__)


class AgentRunner:
    """
    AgentRunner coordinates agent execution:
    - performs slot filling via PreconditionResolver
    - invokes the agent's pattern(s) once context is complete
    """

    def __init__(
        self, agent: "Agent", precondition: Optional[PreconditionResolver] = None
    ):
        self.agent = agent
        self.context = AgentContext()
        self.precondition = precondition

        # Pass system prompt to context if agent has one
        if hasattr(agent, "_system_prompt") and agent._system_prompt:
            self.context.state["system_prompt"] = agent._system_prompt

    async def run(self, task: str) -> dict[str, Any]:
        """
        Main entry point for executing a task.

        - Resolves missing inputs first (via resolver or pattern return)
        - Executes the first available agent pattern
        """
        # Phase 1: fill required fields (if resolver provided)
        while self.precondition:
            check = self.precondition.resolve(self.context)
            if not check:
                break
            print(f"[Agent asks] {check['question']}")
            user_input = input("[Your answer] ")
            self.context.state[check["field"]] = user_input

        # Phase 2: execute pattern
        pattern_errors = []

        for i, pattern in enumerate(self.agent.patterns):
            try:
                logger.info(
                    f"Executing pattern {i + 1}/{len(self.agent.patterns)}: {pattern.__class__.__name__}"
                )

                result = await pattern.run(
                    task=task,
                    memory=self.agent.memory,
                    tools=self.agent.tools,
                    context=self.context,
                )

                # If pattern asks for additional input, loop again
                while result.get("need_user_input"):
                    print(f"[Agent asks] {result['question']}")
                    user_input = input("[Your answer] ")
                    self.context.state[result["field"]] = user_input
                    result = await pattern.run(
                        task=task,
                        memory=self.agent.memory,
                        tools=self.agent.tools,
                        context=self.context,
                    )

                if result.get("success"):
                    logger.info(f"Pattern {pattern.__class__.__name__} succeeded")
                    return result
                else:
                    error_msg = result.get(
                        "error", "Pattern failed without specific error"
                    )
                    logger.error(
                        f"Pattern {pattern.__class__.__name__} failed: {error_msg}"
                    )
                    pattern_errors.append(
                        {
                            "pattern": pattern.__class__.__name__,
                            "error": error_msg,
                            "result": result,
                        }
                    )

            except AgentException as e:
                # Handle our custom exceptions differently
                error_msg = str(e)
                logger.error(
                    f"Pattern {pattern.__class__.__name__} failed: {error_msg}",
                    exc_info=True,
                )

                pattern_errors.append(
                    {
                        "pattern": pattern.__class__.__name__,
                        "error": error_msg,
                        "exception_type": e.__class__.__name__,
                        "exception_context": e.context,
                        "exception_cause": str(e.cause) if e.cause else None,
                        "exception_dict": e.to_dict(),
                        # Add full traceback for better debugging
                        "full_traceback": self._get_full_traceback(e)
                        if isinstance(e, Exception)
                        else "Non-Exception error: " + str(e),
                    }
                )
            except (ValueError, KeyError, TypeError) as e:
                # Data validation and format errors
                error_msg = f"Pattern {pattern.__class__.__name__} data validation error: {str(e)}"
                logger.error(error_msg, exc_info=True)
                pattern_errors.append(
                    {
                        "pattern": pattern.__class__.__name__,
                        "error": error_msg,
                        "exception_type": e.__class__.__name__,
                        "exception_category": "validation_error",
                    }
                )
            except RuntimeError as e:
                # Runtime errors
                error_msg = (
                    f"Pattern {pattern.__class__.__name__} runtime error: {str(e)}"
                )
                logger.error(error_msg, exc_info=True)
                pattern_errors.append(
                    {
                        "pattern": pattern.__class__.__name__,
                        "error": error_msg,
                        "exception_type": e.__class__.__name__,
                        "exception_category": "runtime_error",
                    }
                )
            except Exception as e:
                # Other unknown errors, log but don't re-raise to let other patterns execute
                error_msg = (
                    f"Pattern {pattern.__class__.__name__} unexpected error: {str(e)}"
                )
                logger.error(error_msg, exc_info=True)
                pattern_errors.append(
                    {
                        "pattern": pattern.__class__.__name__,
                        "error": error_msg,
                        "exception_type": e.__class__.__name__,
                        "exception_category": "unexpected_error",
                    }
                )

        # All patterns failed - return detailed error information
        error_summary = (
            f"All {len(self.agent.patterns)} patterns failed or were incomplete."
        )
        logger.error(error_summary)
        for error in pattern_errors:
            logger.error(f"  - {error['pattern']}: {error['error']}")

        return {
            "success": False,
            "error": error_summary,
            "pattern_errors": pattern_errors,
            "patterns_attempted": len(self.agent.patterns),
        }

    def _get_full_traceback(self, exception: Exception) -> str:
        """获取异常的完整回溯信息，包括链接的异常。"""
        # Get the current exception info
        exc_type, exc_value, exc_traceback = (
            type(exception),
            exception,
            exception.__traceback__,
        )

        # Format the traceback
        traceback_str = "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        )

        # If there's a chained exception (cause), include its traceback too
        if exception.__cause__ and isinstance(exception.__cause__, Exception):
            cause_traceback = self._get_full_traceback(exception.__cause__)
            traceback_str += f"\n\nCaused by:\n{cause_traceback}"

        return traceback_str
