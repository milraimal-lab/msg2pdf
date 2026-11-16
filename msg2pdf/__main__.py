"""`python -m msg2pdf` starts the GUI; `python -m msg2pdf --cli ...` runs the command-line version."""

import sys

if len(sys.argv) > 1 and sys.argv[1] == "--cli":
    from .cli import main

    sys.exit(main(sys.argv[2:]))
else:
    from .app import main

    main()
