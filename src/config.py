import importlib.util
import os
import pathlib
import sys
from typing import Optional, Type
import enum

CONFIG_FILE_PATH = os.environ.get("APP_CONFIG_PATH")
if not CONFIG_FILE_PATH:
    # Default path if env var is not set
    CONFIG_FILE_PATH = "../config.py"

config_path = pathlib.Path(__file__).parent / CONFIG_FILE_PATH
config_path = config_path.resolve()  # Resolve any symlinks and get the absolute path

if not config_path.exists():
    raise FileNotFoundError(f"Configuration file not found at: {config_path}")

spec = importlib.util.spec_from_file_location("app_config", config_path)

if spec is None or spec.loader is None:
    raise ImportError(f"Module spec loader is None for {config_path}")

config_module = importlib.util.module_from_spec(spec)

spec.loader.exec_module(config_module)

sys.modules[spec.name] = config_module

GOOGLE_API: str = config_module.GOOGLE_API
FIRECRAWL_APIS: list[tuple[Optional[int], Optional[str]]] = config_module.FIRECRAWL_APIS
FIRECRAWL_ENDPOINT: Optional[str] = config_module.FIRECRAWL_ENDPOINT
AI_DIR: pathlib.Path = config_module.AI_DIR
USR_NAME: str = config_module.USR_NAME
ABOUT_YOU: str = config_module.ABOUT_YOU
MAX_RETRIES: int = config_module.MAX_RETRIES
RETRY_DELAY: int | float = config_module.RETRY_DELAY
MODEL_TOOL_SELECTOR: str = config_module.MODEL_TOOL_SELECTOR
Models: Type[enum.Enum] = config_module.Models
model_RPM_map: dict[str, int] = config_module.model_RPM_map
SearchGroundingSuportedModels: list[str] = config_module.SearchGroundingSuportedModels
ToolSuportedModels: list[str] = config_module.ToolSuportedModels
DynamicThinkingModels: list[str] = config_module.DynamicThinkingModels
ModelsSet: list[str] = config_module.ModelsSet
ABOUT_MODELS: str = config_module.ABOUT_MODELS
CHAT_AI_TEMP: float = config_module.CHAT_AI_TEMP
