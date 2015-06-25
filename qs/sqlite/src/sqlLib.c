
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <errno.h>
#include <syslog.h>

#include "sqlite3.h"
#include "sqlLib.h"

static int sqlite2errno(int err);

SqlStmt_t* sqlLib_createStmt(sqlite3 *db, const char *cmd) {
    bool success = true;
    int32_t rc;
    SqlStmt_t *stmt;

    stmt = (SqlStmt_t*) malloc(sizeof(SqlStmt_t));
    if (NULL == stmt) {
        success = false;
    }

    if (true == success) {
        stmt->cmd = strdup(cmd);
        if (NULL == stmt->cmd) {
            success = false;
            free(stmt);
        }
    }

    if (true == success) {
        /* Create the prepared statement */
        rc = sqlite3_prepare_v2(db, stmt->cmd, strlen(stmt->cmd), &stmt->stmt, NULL);
        if (SQLITE_OK != rc) {
            success = false;
            errno = sqlite2errno(rc);
            free((void*)stmt->cmd);
            free(stmt);
        }
    }

    if (true == success) {
        /* Now create the mutex for this statement */
        rc = pthread_mutex_init(&stmt->lock, NULL);
        if (0 != rc) {
            success = false;
            (void)sqlite3_finalize(stmt->stmt);
            free((void*)stmt->cmd);
            free(stmt);
        }
    }

    return stmt;
} /* SqlStmt_t* sqlLib_createStmt(sqlite3 *db, char *cmd) */

void sqlLib_deleteStmt(SqlStmt_t **stmtPtr) {
    SqlStmt_t *stmt;
    int32_t rc;

    if (NULL != stmtPtr) {
        stmt = *stmtPtr;
        /* A statement may not be fully initialized, if it isn't don't bother trying 
         * to lock the mutex or finalize the SQLite statement */
        if ((NULL != stmt) && (NULL != stmt->stmt)) {
            /* lock the mutex to prevent another thread from using the statement 
             * while it is being cleaned up. */
            rc = pthread_mutex_lock(&stmt->lock);

            /* No need to check the error code from this, it will just be the last 
             * error (if any) from the last time the statement was executed. */
            (void)sqlite3_finalize(stmt->stmt);

            /* If the mutex was locked successfully, unlock it before destroying the 
             * mutex. */
            if (0 == rc) {
                (void)pthread_mutex_unlock(&stmt->lock);
            }

            (void)pthread_mutex_destroy(&stmt->lock);
        }

        /* Always attempt to free the stmt */
        if (NULL != stmt) {
            free((void*)stmt->cmd);
        }
        free(stmt);

        *stmtPtr = NULL;
    }
} /* void sqlLib_deleteStmt(SqlStmt_t **stmt) */

static int sqlite2errno(int sqlErr) {
    int err;

    if          (SQLITE_OK == sqlErr) {
        err = 0;
    } else if   (SQLITE_INTERNAL == sqlErr) {
        err = EFAULT;
    } else if   (SQLITE_PERM == sqlErr) {
        err = EPERM;
    } else if   (SQLITE_ABORT == sqlErr) {
        err = ECONNABORTED;
    } else if   (SQLITE_BUSY == sqlErr) {
        err = EBUSY;
    } else if   (SQLITE_LOCKED == sqlErr) {
        err = ENOLCK;
    } else if   (SQLITE_NOMEM == sqlErr) {
        err = ENOMEM;
    } else if   (SQLITE_READONLY == sqlErr) {
        err = EROFS;
    } else if   (SQLITE_INTERRUPT == sqlErr) {
        err = EINTR;
    } else if   (SQLITE_IOERR == sqlErr) {
        err = EIO;
    } else if   (SQLITE_CORRUPT == sqlErr) {
        err = EBADF;
    } else if   (SQLITE_NOTFOUND == sqlErr) {
        err = EBADRQC;
    } else if   (SQLITE_FULL == sqlErr) {
        err = ENOSPC;
    } else if   (SQLITE_CANTOPEN == sqlErr) {
        err = ENOENT;
    } else if   (SQLITE_PROTOCOL == sqlErr) {
        err = EPROTO;
    } else if   (SQLITE_EMPTY == sqlErr) {
        err = ENODATA;
    } else if   (SQLITE_SCHEMA == sqlErr) {
        err = EPIPE;
    } else if   (SQLITE_TOOBIG == sqlErr) {
        err = E2BIG;
    } else if   (SQLITE_CONSTRAINT == sqlErr) {
        err = EINVAL;
    } else if   (SQLITE_MISMATCH == sqlErr) {
        err = EPROTOTYPE;
    } else if   (SQLITE_MISUSE == sqlErr) {
        err = ELIBBAD;
    } else if   (SQLITE_NOLFS == sqlErr) {
        err = ENOSYS;
    } else if   (SQLITE_AUTH == sqlErr) {
        err = EACCES;
    } else if   (SQLITE_FORMAT == sqlErr) {
        err = ELIBBAD;
    } else if   (SQLITE_RANGE == sqlErr) {
        err = ERANGE;
    } else if   (SQLITE_NOTADB == sqlErr) {
        err = EBFONT;
    } else if   (SQLITE_NOTICE == sqlErr) {
        err = ENOTSUP;
    } else if   (SQLITE_WARNING == sqlErr) {
        err = ENOTSUP;
    } else {
        err = ELOOP;
    };

    return err;
} /* static int sqlite2errno(int err) */

