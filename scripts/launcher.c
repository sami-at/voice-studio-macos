#include <mach-o/dyld.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>

/* Finder gives no console, so a failure before launch needs a native dialog. */
static int fail(const char *message) {
    char script[1024];
    snprintf(script, sizeof(script), "display dialog \"%s\" with title \"Voice Studio\" "
             "buttons {\"OK\"} default button 1 with icon stop", message);
    execl("/usr/bin/osascript", "osascript", "-e", script, (char *)NULL);
    fprintf(stderr, "%s\n", message);
    return 1;
}

int main(void) {
    char executable[PATH_MAX], root[PATH_MAX], manifest[PATH_MAX], python[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size)) return 1;
    char *slash = strrchr(executable, '/');
    if (!slash) return 1;
    *slash = 0;
    snprintf(manifest, sizeof(manifest), "%s/../Resources/project-path.txt", executable);
    FILE *f = fopen(manifest, "r");
    if (!f || !fgets(root, sizeof(root), f)) {
        if (f) fclose(f);
        return fail("This copy of Voice Studio has no project folder recorded. Rebuild it with "
                    "Install Voice Studio.command.");
    }
    fclose(f);
    root[strcspn(root, "\r\n")] = 0;
    if (chdir(root))
        return fail("The Voice Studio project folder has moved or been renamed. Double-click "
                    "Install Voice Studio.command inside the project folder to rebuild this launcher.");
    snprintf(python, sizeof(python), "%s/.venv/bin/python", root);
    if (access(python, X_OK))
        return fail("The Voice Studio Python environment is missing. Double-click "
                    "Install Voice Studio.command in the project folder, then open Voice Studio again.");
    mkdir("local_data", 0700);
    mkdir("local_data/logs", 0700);
    int log = open("local_data/logs/desktop.log", O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (log >= 0) { dup2(log, 1); dup2(log, 2); close(log); }
    setenv("PYTHONUNBUFFERED", "1", 1);
    setenv("__CFBundleIdentifier", "local.voicestudio.desktop", 1);
    char *args[] = {python, "app.py", NULL};
    execv(python, args);
    return fail("Voice Studio could not start its Python environment. Double-click "
                "Install Voice Studio.command in the project folder to repair it.");
}
