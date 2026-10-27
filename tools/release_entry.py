"""Entry script for the self-contained release build (tools/build_release.sh).

PyInstaller needs a plain script rather than `-m datetree`. The frozen app is
GUI-only; the date-inspection CLI stays a source-checkout feature.
"""

from datetree.gui import main

main()
