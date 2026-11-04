# SPDX-License-Identifier: MIT
"""Lazy exports: Explorer handoffs do not load converters or Tk."""
from importlib import import_module
__version__ = '1.0.0'
PUBLISHER = 'AlsherkawiMO'
INSTAGRAM_URL = 'https://instagram.com/alsherkawiMO'
_EXPORTS = {'Client': 'sdk','ConverterEngine': 'engine', 'QueueItem': 'engine',
            'ConversionOptions': 'options', 'ConversionService': 'jobs',
            'JobHandle': 'jobs', 'get_default_service': 'jobs'}
__all__ = [*_EXPORTS, '__version__']
def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module('.' + _EXPORTS[name], __name__), name)
    globals()[name] = value
    return value
