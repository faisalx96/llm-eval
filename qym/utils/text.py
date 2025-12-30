"""Text utilities for proper RTL/Arabic text rendering in terminals."""

import arabic_reshaper
from bidi.algorithm import get_display


def arabic_display(text: str) -> str:
    """
    Prepare Arabic/RTL text for correct display in terminals.
    
    Most terminals don't support Unicode BiDi control characters,
    so we algorithmically reorder the text for LTR display.
    
    Args:
        text: Arabic text to prepare for display
        
    Returns:
        Text reordered for correct visual display in LTR terminals
    """
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

