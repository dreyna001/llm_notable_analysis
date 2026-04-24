"""On-prem deployment wrapper for the updated notable-analysis core."""

from .config import OnPremRuntimeConfig
from .context_provider import LocalJsonAdvisoryContextProvider
from .file_io import LocalJsonFileTransport, StdlibLocalJsonFileTransport
from .runner import EmptyContextProvider, LiteLlmTransport, OnPremLiteLlmCoreRunner
from .service import (
    CoreAnalysisRunner,
    OnPremNotableProcessor,
    build_default_processor,
)
from .worker import (
    HttpReadinessProbe,
    NotableProcessor,
    OnPremWorker,
    ReadinessProbe,
    StopSignal,
    build_default_worker,
    install_stop_signal_handlers,
)

__all__ = [
    "CoreAnalysisRunner",
    "EmptyContextProvider",
    "HttpReadinessProbe",
    "LiteLlmTransport",
    "LocalJsonFileTransport",
    "LocalJsonAdvisoryContextProvider",
    "NotableProcessor",
    "OnPremNotableProcessor",
    "OnPremRuntimeConfig",
    "OnPremLiteLlmCoreRunner",
    "OnPremWorker",
    "ReadinessProbe",
    "StdlibLocalJsonFileTransport",
    "StopSignal",
    "build_default_processor",
    "build_default_worker",
    "install_stop_signal_handlers",
]
