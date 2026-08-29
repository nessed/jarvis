"""Local Whisper large-v3 STT on the Ryzen AI NPU (blueprint 3.1).

The backend lives in :mod:`voice.whisper.local_backend`; import it from there::

    from voice.whisper.local_backend import LocalWhisperBackend

This file deliberately re-exports nothing. Importing the submodule here would
make ``python -m voice.whisper.local_backend`` -- how the runtime is checked
from a shell -- emit a ``RuntimeWarning`` about the module already being in
``sys.modules``, and a warning printed above every availability check is a
warning nobody reads.

Nothing in this package imports an audio library or touches a device at import
time. The build tree, the FlexML runtime and the model weights it consumes are
all untracked; see ``docs/tasks/whisper-npu-build-report.md``.
"""
