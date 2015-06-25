
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <syslog.h>
#include <sys/stat.h>
#include <sys/file.h>
#include "mcp.h"

#define PID_DIR "/var/run"

static int32_t daemonize(pid_t *pid) __attribute__ ((unused));
static int32_t closeFDs(void);
static int32_t openPidFile(char *name, pid_t pid, char **pidfile);
static void closePidFile(int32_t fd, char *name);

/* Steps to startup a *nix daemon:
 *  1. Fork off the parent process
 *  2. Change file mode mask (umask)
 *  3. Open any logs for writing
 *  4. Create a unique Session ID (SID)
 *  5. Change the current working directory to a safe place
 *  6. Close standard file descriptors
 *  7. Enter actual daemon code
 */
int32_t main(int UNUSED(argc), char UNUSED(*argv[])) {
    int32_t fd, rc = 0;
    pid_t pid;
    char *daemonName = NULL, *pidFileName = NULL;

    openlog(DAEMON_NAME, LOG_CONS, LOG_LOCAL0);

#ifndef DEBUG
    rc = daemonize(&pid);
#else
    pid = getpid();
#endif

    if (0 == rc) {
        /* Use a local log type for the MCP daemon */
        (void)asprintf(&daemonName, "%s[%d]", DAEMON_NAME, pid);
        closelog();
        openlog(daemonName, LOG_CONS, LOG_LOCAL0);

        fd = openPidFile(DAEMON_NAME, pid, &pidFileName);
        if (0 >= fd) {
            rc = -1;
        }
    }

    /* Start MCP */
    if (0 == rc) {
        if (true == mcp_start()) {
            syslog(LOG_NOTICE, DAEMON_NAME " started...");
            mcp_run();
        }
    }

    closePidFile(fd, pidFileName);

    if (0 == rc) {
        syslog(LOG_NOTICE, "exiting...");
    } else {
        syslog(LOG_ALERT, "startup errors detected, exiting...");
    }

    closelog();

    if (NULL != daemonName) {
        free(daemonName);
    }
    exit(rc);
} /* int32_t main(int argc, char *argv[]) */

static int32_t daemonize(pid_t *pid) {
    int32_t rc;

    /* Fork off the parent process */
    errno = 0;
    *pid = fork();
    if (0 > *pid) {
        syslog(LOG_ERR, "%s:%d error forking (%d:%s)",
               __FUNCTION__, __LINE__, errno, strerror(errno));
    } else if (0 < *pid) {
        /* Exit the parent process */
        exit(EXIT_SUCCESS);
    } else {
        /* This is the child process */
        rc = 0;
    }

    if (0 == rc) {
        /* Change the file mode mask, we don't care what the previous umask was so 
         * just ignore it, the umask() function never fails. */
        (void)umask(0);

        /* Create a new SID for the child process */
        *pid = setsid();
        if (0 > *pid) {
            syslog(LOG_ERR, "%s:%d error creating new sid (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
        }
    }

    if (0 == rc) {
        /* Change the current working directory */
        if (0 > chdir("/")) {
            syslog(LOG_ERR, "%s:%d error changing to \"%s\" dir (%d:%s)",
                   __FUNCTION__, __LINE__, "/", errno, strerror(errno));
        }
    }

    if (0 == rc) {
        rc = closeFDs();
    }

    return rc;
} /* static int32_t daemonize(pid_t *pid) */

static int32_t closeFDs(void) {
    int32_t rc;

    errno = 0;

    /* The STDOUT, STDERR, and STDIN streams cannot be used by a daemon, close 
     * them and redirect them to /dev/null (in case the code tries to use them 
     * by accident) */
    rc = close(STDIN_FILENO);
    if (0 > rc) {
        syslog(LOG_ERR, "%s:%d failed to close standard stream %d (%d:%s)",
               __FUNCTION__, __LINE__, STDIN_FILENO, errno, strerror(errno));
    }

    if (0 == rc) {
        rc = close(STDOUT_FILENO);
        if (0 > rc) {
            syslog(LOG_ERR, "%s:%d failed to close standard stream %d (%d:%s)",
                   __FUNCTION__, __LINE__, STDOUT_FILENO, errno, strerror(errno));
        }
    }

    if (0 == rc) {
        rc = close(STDERR_FILENO);
        if (0 > rc) {
            syslog(LOG_ERR, "%s:%d failed to close standard stream %d (%d:%s)",
                   __FUNCTION__, __LINE__, STDERR_FILENO, errno, strerror(errno));
        }
    }

    /* There should be no file descriptors open, so the first one opened should 
     * be STDIN_FILENO */
    if (0 == rc) {
        rc = open("/dev/null", O_RDWR);
        if (STDIN_FILENO != rc) {
            syslog(LOG_ERR, "%s:%d error opening \"%s\" as stream %d (%d:%s)",
                   __FUNCTION__, __LINE__, "/dev/null", STDIN_FILENO, errno, strerror(errno));
        } else {
            rc = 0;
        }
    }

    if (0 == rc) {
        rc = dup2(STDIN_FILENO, STDOUT_FILENO);
        if (STDOUT_FILENO != rc) {
            syslog(LOG_ERR, "%s:%d error duping stream %d to %d (%d:%s)",
                   __FUNCTION__, __LINE__, STDIN_FILENO, STDOUT_FILENO, errno, strerror(errno));
        } else {
            rc = 0;
        }
    }

    if (0 == rc) {
        rc = dup2(STDIN_FILENO, STDERR_FILENO);
        if (STDERR_FILENO != rc) {
            syslog(LOG_ERR, "%s:%d error duping stream %d to %d (%d:%s)",
                   __FUNCTION__, __LINE__, STDIN_FILENO, STDERR_FILENO, errno, strerror(errno));
        } else {
            rc = 0;
        }
    }

    return rc;
} /* static int32_t closeFDs(void) */

static int32_t openPidFile(char *name, pid_t pid, char **pidfile) {
    int32_t fd, rc = 0;
    char *pidStr = NULL;

    errno = 0;
    rc = asprintf(pidfile, PID_DIR "/%s.pid", name);
    if (0 > rc) {
        syslog(LOG_ERR, "%s:%d error allocating string for pidfile name (%d:%s)",
               __FUNCTION__, __LINE__, errno, strerror(errno));
    } else if (NULL == pidfile) {
        rc = -1;
    } else {
        rc = 0;
    }

    if (0 == rc) {
        errno = 0;
        fd = open(*pidfile, O_RDWR | O_CREAT | O_EXCL, DEFFILEMODE);

        if ((0 >= fd) && (EEXIST == errno)) {
            syslog(LOG_DEBUG, "%s:%d pidfile \"%s\" exists, opening existing pidfile",
                   __FUNCTION__, __LINE__, *pidfile);
            errno = 0;
            fd = open(*pidfile, O_RDWR, DEFFILEMODE);
        }

        if (0 >= fd) {
            rc = -1;
            syslog(LOG_ERR, "%s:%d unable to open pidfile \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, *pidfile, errno, strerror(errno));
        }
    }

    if (0 == rc) {
        rc = asprintf(&pidStr, "%d", pid);
        if (0 > rc) {
            syslog(LOG_ERR, "%s:%d error allocating string for pid string (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
        } else {
            rc = 0;
        }
    }

    if (0 == rc) {
        rc = write(fd, pidStr, strlen(pidStr));
        if ((int32_t)strlen(pidStr) != rc) {
            syslog(LOG_ERR, "%s:%d error writing pid %d to pidfile \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, pid, *pidfile, errno, strerror(errno));
        } else {
            rc = 0;
        }
    }

    if (NULL != pidStr) {
        free(pidStr);
    }

    if (0 == rc) {
        rc = flock(fd, LOCK_EX);
        if (0 > rc) {
            syslog(LOG_ERR, "%s:%d error locking pidfile \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, *pidfile, errno, strerror(errno));
        } else {
            rc = 0;
        }
    }

    if (0 == rc) {
        rc = fd;
    } else {
        if (NULL != *pidfile) {
            free(*pidfile);
        }
        *pidfile = NULL;
    }

    return fd;
} /* static int32_t openPidFile(char *name, pid_t pid, char **pidfile) */

static void closePidFile(int32_t fd, char *name) {
    /* If the pidfile was opened, the name will not be null, if it is NULL, 
     * there is nothing to do. */
    if (NULL != name) {
        /* Regardless of any detected errors, continue the process of closing 
         * and removing the pidfile. */
        errno = 0;
        if (0 > flock(fd, LOCK_UN)) {
            syslog(LOG_ERR, "%s:%d error unlocking pidfile \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, name, errno, strerror(errno));
        }

        errno = 0;
        if (0 > close(fd)) {
            syslog(LOG_ERR, "%s:%d error closing pidfile \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, name, errno, strerror(errno));
        }

        errno = 0;
        if (0 > remove(name)) {
            syslog(LOG_ERR, "%s:%d error removing pidfile \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, name, errno, strerror(errno));
        }

        if (NULL != name) {
            free(name);
        }
    }
} /* static void closePidFile(int32_t fd, char *name) */

