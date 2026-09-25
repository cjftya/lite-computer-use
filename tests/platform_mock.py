"""Isolate a simulated Windows platform from Python and pytest internals."""

from contextlib import ExitStack, contextmanager
import importlib
import os
import sys
from types import ModuleType
from unittest.mock import patch


@contextmanager
def simulated_windows_os(*module_names):
    """Set os.name only on product modules, leaving pathlib's host OS intact."""
    fake_os = ModuleType("os")
    fake_os.__dict__.update(vars(os))
    fake_os.name = "nt"
    if module_names:
        modules = [importlib.import_module(name) for name in module_names]
    else:
        modules = [module for name, module in tuple(sys.modules.items())
                   if name.startswith("scripts.lcu.") and getattr(module, "os", None) is os]
    with ExitStack() as stack:
        for module in modules:
            stack.enter_context(patch.object(module, "os", fake_os))
        yield
