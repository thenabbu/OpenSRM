"""Stub for cv2 -- real OpenCV removed from image.

ddddocr imports cv2 at module load time, but its slide-captcha and
color-filter code paths (the only ones that actually call cv2) are
never exercised by DdddOcr(beta=True).classification(), which is the
only ddddocr method this app calls.

This stub lets import cv2 succeed silently, and fails loudly if a
real cv2 function is ever actually called.
"""

class _StubModule:
    def __getattr__(self, name):
        def _raise(*a, **k):
            raise RuntimeError(
                f"cv2.{name}() called on the opencv stub. Real OpenCV "
                "was intentionally not installed. If a code path now "
                "genuinely needs it, install opencv-python-headless."
            )
        return _raise

import sys as _sys
_stub = _StubModule()
_sys.modules[__name__] = _stub
