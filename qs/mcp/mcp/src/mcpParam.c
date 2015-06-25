
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <pthread.h>
#include <errno.h>
#include <semaphore.h>
#include "sqlite3.h"
#include "mcp.h"
#include "mcpDb.h"
#include "mcpParam.h"

/* tables relevant to this module:
 *  CREATE TABLE paramTable (
 *      id          INTEGER PRIMARY KEY AUTOINCREMENT,
 *      name        TEXT,
 *      type        TEXT,
 *      port        TEXT
 *  );
 */

static pthread_mutex_t m_paramValidLock = PTHREAD_MUTEX_INITIALIZER;

static sqlite3_stmt *m_paramValidStmt;

bool mcpParam_initialize(void) {
    bool success = true;
    const char *cmd;
    int32_t rc;

    /* Prepare the parameter value retrieval statement, the first variable 
     * is the parameter ID. */
    cmd = "SELECT 1 FROM paramTable WHERE id == ?;";
    rc = sqlite3_prepare_v2(g_mct, cmd, strlen(cmd), &m_paramValidStmt, NULL);
    if (SQLITE_OK != rc) {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error preparing statement \"%s\" (%d:%s)",
               __FUNCTION__, __LINE__, cmd, rc, sqlite3_errstr(rc));
    }

    return success;
} /* bool mcpParam_initialize(void) */

void mcpParam_shutdown(void) {
    (void) sqlite3_finalize(m_paramValidStmt);
} /* void mcpParam_shutdown(void) */

bool mcpParam_set(uint32_t id, double value) {
    bool success = true;

    success = mcpParam_valid(id);
    if (true == success) {
        errno = 0;
        if (0 == sem_wait(g_mcpShmSem)) {
            /* The parameter ID is 1 based, subtract 1 to get the param index */
            g_mcpShm->params[id - 1] = value;

            errno = 0;
            if (0 != sem_post(g_mcpShmSem)) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d sem_post() error (%d:%s)",
                       __FUNCTION__, __LINE__, errno, strerror(errno));
            }
        } else {
            success = false;
            mcp_log(LOG_ERR, "%s:%d sem_wait() error (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
        }
    } else {
        mcp_log(LOG_ERR, "%s:%d param %u is not valid (%d:%s)",
               __FUNCTION__, __LINE__, id, errno, strerror(errno));
    }

    return success;
} /* bool mcpParam_set(uint32_t id, double value) */

bool mcpParam_get(uint32_t id, double *value) {
    bool success = true;

    success = mcpParam_valid(id);
    if (true == success) {
        errno = 0;
        if (0 == sem_wait(g_mcpShmSem)) {
            /* The parameter ID is 1 based, subtract 1 to get the param index */
            *value = g_mcpShm->params[id - 1];

            errno = 0;
            if (0 != sem_post(g_mcpShmSem)) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d sem_post() error (%d:%s)",
                       __FUNCTION__, __LINE__, errno, strerror(errno));
            }
        } else {
            success = false;
            mcp_log(LOG_ERR, "%s:%d sem_wait() error (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
        }
    } else {
        mcp_log(LOG_ERR, "%s:%d param %u is not valid (%d:%s)",
               __FUNCTION__, __LINE__, id, errno, strerror(errno));
    }

    return success;
} /* bool mcpParam_get(uint32_t id, double *value) */

bool mcpParam_valid(uint32_t id) {
    bool success = true;
    int32_t rc;

    rc = pthread_mutex_lock(&m_paramValidLock);
    if (0 == rc) {
        rc = sqlite3_reset(m_paramValidStmt);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error resetting statement, (%d:%s)",
                   __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
        }

        if (true == success) {
            rc = sqlite3_bind_int(m_paramValidStmt, 1, id);
            if (SQLITE_OK != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error binding id %d to param %d, (%d:%s)",
                       __FUNCTION__, __LINE__, id, 1, rc, sqlite3_errstr(rc));
            }
        }

        if (true == success) {
            rc = sqlite3_step(m_paramValidStmt);
            if (SQLITE_DONE == rc) {
                /* a return code of SQLITE_DONE means no rows were found, so this 
                 * param is invalid. */
                success = false;
            } else if (SQLITE_ROW != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error executing prepared statement (%d:%s)",
                       __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
            } else if (0 == sqlite3_column_count(m_paramValidStmt)) {
                success = false;
            }
        }

        rc = pthread_mutex_unlock(&m_paramValidLock);
        if (0 != rc) {
            fprintf(stderr, "%s:%d error unlocking mutex (%d:%s)\n",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else /* !(0 == rc) */ {
        success = false;
        fprintf(stderr, "%s:%d error locking mutex (%d:%s)\n",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    return success;
} /* bool mcpParam_valid(uint32_t id) */

