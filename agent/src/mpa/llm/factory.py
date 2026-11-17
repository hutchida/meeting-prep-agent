from __future__ import annotations

from mpa.contract import LLMClient, Settings
from mpa.llm.litellm import LiteLLMClient
from mpa.llm.replay import RecordingClient, ReplayClient


def build_llm_client(settings: Settings) -> LLMClient:
    """Live: LiteLLMClient (recorded when RECORD is set); replay: ReplayClient."""
    if settings.llm_mode == "replay":
        return ReplayClient(
            settings.recordings_dir, settings.replay_delay_ms, model=settings.llm_model
        )
    live = LiteLLMClient(settings)
    if settings.record:
        return RecordingClient(live, settings.recordings_dir, model=settings.llm_model)
    return live
