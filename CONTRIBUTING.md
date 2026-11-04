# Contributing to PuryF

Use Python 3.10 or newer with Tkinter. Create a virtual environment and install `requirements.txt`.
Run `python -m unittest discover -s tests -v` before submitting changes.

Keep conversion work off the UI thread. Communicate UI updates through the existing queue.
Preserve source-file safety, password exclusion from sessions and optional dependency checks.
Changes to scrolling should be tested with real mouse/touchpad input on the affected Windows/Tk version.
Add tests for meaningful behavior changes and describe any external programs needed to reproduce them.

Use small, focused changes. Explain what problem the change solves and what was verified.
Contributions are submitted under this project's MIT license.

The release package is ready to upload to a repository, but no public repository is configured yet.
