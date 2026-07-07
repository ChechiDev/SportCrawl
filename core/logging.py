"""Structured logging configuration for fbrefly.

Call configure_logging(env, log_level) once at application startup.
Use bind_context(domain, operation) to get a logger with contextual fields.

Modules use: import logging; logger = logging.getLogger(__name__)
No print() statements anywhere in the codebase.
"""

import logging
from typing import Any, Literal, cast

import structlog
from structlog.types import FilteringBoundLogger

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def configure_logging(env: Literal["dev", "prod"], log_level: str) -> None:
    """Configure structlog and stdlib logging for the given environment.

    Args:
        env: "dev" for colored console output, "prod" for JSON output.
        log_level: One of "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL".
    """
    if log_level.upper() not in _VALID_LOG_LEVELS:
        valid = sorted(_VALID_LOG_LEVELS)
        raise ValueError(f"Invalid log_level: {log_level!r}. Must be one of {valid}")
    level = getattr(logging, log_level.upper())

    # list[Any] is required: structlog processors implement different protocols
    # (Processor, WrappedLogger) with no shared public base type in structlog stubs.
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if env == "prod":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logging.basicConfig(
        handlers=[handler],
        level=level,
        force=True,
    )


def bind_context(domain: str, operation: str) -> FilteringBoundLogger:
    """Return a structlog logger bound with domain and operation context.

    Args:
        domain: The domain name (e.g., "player", "club").
        operation: The operation name (e.g., "fetch", "parse").

    Returns:
        A structlog bound logger with domain and operation fields set.
    """
    # cast required: structlog.get_logger().bind() returns BoundLoggerLazyProxy at
    # runtime, which conforms to FilteringBoundLogger but is not typed as such in stubs.
    return cast(
        FilteringBoundLogger,
        structlog.get_logger().bind(domain=domain, operation=operation),
    )
