"""Voice Studio desktop entry point; inference runs in a separate process."""
import subprocess
import sys
import traceback


def report(message):
    """Launched from Finder there is no console, so say it in a native dialog."""
    traceback.print_exc(file=sys.stderr)
    subprocess.run(['/usr/bin/osascript', '-e', 'display dialog "%s" with title "Voice Studio" '
                    'buttons {"OK"} default button 1 with icon stop' % message], check=False)
    raise SystemExit(1)


if __name__ == '__main__':
    try:
        from voice_studio.ui import main
    except Exception:
        report('Voice Studio could not load its desktop components. Double-click Install Voice '
               'Studio.command in the project folder to repair the environment.')
    try:
        main()
    except Exception:
        report('Voice Studio stopped unexpectedly. Details are in local_data/logs/desktop.log.')
