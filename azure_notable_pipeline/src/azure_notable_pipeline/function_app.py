"""Thin Azure Functions trigger registration shell."""

from __future__ import annotations

import logging

try:
    import azure.functions as func
except ImportError:  # Phase 0 contract tests do not require runtime packages.
    func = None  # type: ignore[assignment]


app = func.FunctionApp() if func is not None else None
logger = logging.getLogger(__name__)


if app is not None:
    from .blob_handler import (
        normalize_analyzer_queue_message,
        process_blob_created,
        publish_blob_trigger_input,
    )
    from .embed_handler import dispatch_embed_queue_message
    from .disposition_sync_handler import handle_timer
    from .portal_handler import handle_request
    from .queue_monitor import emit_queue_depth_traces

    @app.function_name(name="intake_blob")
    @app.blob_trigger(
        arg_name="source_blob",
        path="%INPUT_CONTAINER_NAME%/incoming/{name}",
        connection="InputStorage",
    )
    def intake_blob(source_blob: func.InputStream) -> None:
        """Extract native Blob properties and publish one strict v1 job."""

        try:
            publish_blob_trigger_input(source_blob)
        except Exception:
            logger.exception("Polling Blob intake failed before durable job publication")
            raise

    @app.function_name(name="analyzer_queue")
    @app.queue_trigger(
        arg_name="message",
        queue_name="%ANALYZER_QUEUE_NAME%",
        connection="OutputStorage",
    )
    def analyzer_queue(message: func.QueueMessage) -> None:
        """Validate the application job before invoking analyzer orchestration."""

        try:
            intake = normalize_analyzer_queue_message(message.get_body())
            process_blob_created(intake)
        except Exception:
            logger.exception("Analyzer queue processing failed")
            raise

    @app.function_name(name="case_embed_queue")
    @app.queue_trigger(
        arg_name="message",
        queue_name="%CASE_EMBED_QUEUE_NAME%",
        connection="OutputStorage",
    )
    def case_embed_queue(message: func.QueueMessage) -> None:
        """Validate a v1 embed job before native workflow dispatch."""

        try:
            dispatch_embed_queue_message(message.get_body())
        except Exception:
            logger.exception("Case embed queue processing failed")
            raise

    @app.function_name(name="disposition_sync_timer")
    @app.timer_trigger(
        arg_name="timer",
        schedule="0 0 0 * * *",
        run_on_startup=False,
        use_monitor=True,
    )
    def disposition_sync_timer(timer: func.TimerRequest) -> None:
        """Run the daily native ServiceNow disposition synchronization pass."""

        try:
            handle_timer(timer)
        except Exception:
            logger.exception("ServiceNow disposition timer processing failed")
            raise

    @app.function_name(name="operations_monitor_timer")
    @app.timer_trigger(
        arg_name="timer",
        schedule="0 */5 * * * *",
        run_on_startup=False,
        use_monitor=True,
    )
    def operations_monitor_timer(timer: func.TimerRequest) -> None:
        """Emit per-queue depth traces for poison and backlog alerting."""

        if timer.past_due:
            logger.warning("Operations queue monitor timer invocation is past due")
        try:
            emit_queue_depth_traces()
        except Exception:
            logger.exception("Operations queue depth polling failed")
            raise

    @app.function_name(name="portal_http")
    @app.route(
        route="{*path}",
        methods=["GET", "POST", "DELETE", "OPTIONS"],
        auth_level=func.AuthLevel.ANONYMOUS,
    )
    def portal_http(request: func.HttpRequest) -> func.HttpResponse:
        """Route native portal requests; application authentication is mandatory."""

        return handle_request(request)
