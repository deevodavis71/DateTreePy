"""Entry point.

    python3 -m datetree                 launch the GUI
    python3 -m datetree FILE [FILE...]  print the date DateTree would file each
                                        file under (useful for spot-checking
                                        the EXIF reader against real NEFs)
"""

import sys
from pathlib import Path

from .exif import capture_date, date_folder
from .gui import main


def show_dates(paths: list[str]) -> int:
    exit_code = 0
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            print(f"{raw}: not a file")
            exit_code = 1
            continue
        day, source = capture_date(path)
        print(f"{date_folder(day)}  ({source})  {path.name}")
    return exit_code


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(show_dates(sys.argv[1:]))
    main()
