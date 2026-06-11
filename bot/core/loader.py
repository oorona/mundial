import os
import importlib
import structlog
from typing import List

logger = structlog.get_logger()


def find_cogs(cogs_dir: str = "cogs") -> List[str]:
    """
    Recursively find all cogs in the given directory.
    Returns a list of extension names (dotted paths).
    """
    cogs = []

    for root, _dirs, files in os.walk(cogs_dir):
        for file in files:
            if not (file.endswith(".py") and not file.startswith("_")):
                continue

            module_path = os.path.join(root, file)[:-3]
            module_name = module_path.replace(os.sep, ".")
            if module_name.startswith("."):
                module_name = module_name[1:]

            cogs.append(module_name)

    return cogs


async def load_cogs(bot, cogs_dir: str = "cogs"):
    """Load all cogs found in the directory."""
    cogs = find_cogs(cogs_dir)
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            logger.info(f"Loaded extension: {cog}")
        except Exception as e:
            logger.error(f"Failed to load extension {cog}: {e}")
