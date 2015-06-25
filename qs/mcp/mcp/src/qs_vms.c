
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <errno.h>
#include <syslog.h>
#include <mysql.h>

#include "mcp.h"

#include "qs_vms.h"

typedef struct VmsDbServerInfo_s {
    char *address;
    uint16_t port;
    char *username;
    char *password;
    char *ca_cert;
    char *db_name;
} VmsDbServerInfo_t;

typedef struct VmsDbConn_s {
    MYSQL *mysql;
    MYSQL_STMT *incr_session_stmt;
    MYSQL_STMT *param_update_stmt;
    MYSQL_STMT *status_update_stmt;
    MYSQL_STMT *app_state_update_stmt;
} VmsDbConn_t;

/* Mapping of VM/Application states to the numeric and string states that should 
 * be set in the QS/VMS database. */
typedef struct VmsDomStateMapping_s {
    uint32_t state_value;
    char *state_string;
} VmsDomStateMapping_t;

/* Here are the meanings of the state ranges that are recognized by the QS/VMS 
 * database:
 *  50: Stored on the ground station (not visible on the gateway, but is on the 
 *      ground station).
 *  80: Stored on the Gateway
 *  100: On the host and operational.
 *  101-199: Operational, on the host, with added messages and states.
 *  200: On the host, but NOT operational.  For example the VM is there, but the 
 *      executable has stopped.  This might be necessary for different modes of 
 *      operation.  Essentially the VM is ready and waiting, but the app is not 
 *      in use.
 *  201-299: similar code to 200
 *  300-399: Error codes; VM and application are on the host
 *
 * Here are specific states expected by QS/VMS at this time:
 *  100: On Host - VM Operational - App Operational
 *  110: On Host - VM Paused - App not running
 *  180: On Host - VM Operational - App Initializing
 *  190: On Host - VM Initializing - App not running
 *  195: On Host - VM Configured - App not running
 *  200: On Host - VM Operational - App Error
 *  205: On Host - VM Operational - Unable to start app
 *  300: On Host - VM Error - App not running
 *
 * The app-specific states (100, 180, 200, and 205) are maintained by the 
 * watchdog service in the domain.
 *
 * When the application is installed on the target (where the MCP service is 
 * running) the installing application/script should set state 195 in QS/VMS.
 *
 * MCP needs to track the 110, 190 and 300 states for now. */
static const VmsDomStateMapping_t m_stateMap[] = {
    [QS_VMS_VM_UNKNOWN] = { 0, "N/A" },
    [QS_VMS_VM_STARTED] = { 190, "On Host - VM Initializing" },
    [QS_VMS_VM_PAUSED]  = { 110, "On Host - VM Paused" },
    [QS_VMS_VM_ERROR]   = { 300, "On Host - VM Error" },
};

static pthread_once_t m_dbOnce = PTHREAD_ONCE_INIT;
static VmsDbConn_t *m_dbData = NULL;
static VmsDbServerInfo_t *m_dbInfo = NULL;

static void vms_init(void);

void vms_close(void) {
    if (NULL != m_dbData) {
        if (NULL != m_dbData->mysql) {
            if (NULL != m_dbData->incr_session_stmt) {
                mysql_stmt_close(m_dbData->incr_session_stmt);
            }
            if (NULL != m_dbData->param_update_stmt) {
                mysql_stmt_close(m_dbData->param_update_stmt);
            }
            if (NULL != m_dbData->status_update_stmt) {
                mysql_stmt_close(m_dbData->status_update_stmt);
            }
            if (NULL != m_dbData->app_state_update_stmt) {
                mysql_stmt_close(m_dbData->app_state_update_stmt);
            }
            mysql_close(m_dbData->mysql);
        }
        m_dbData->mysql = NULL;
        m_dbData->incr_session_stmt = NULL;
        m_dbData->param_update_stmt = NULL;
        m_dbData->status_update_stmt = NULL;
        m_dbData->app_state_update_stmt = NULL;

        free(m_dbData);
        m_dbData = NULL;
    }

    if (NULL == m_dbInfo) {
        free(m_dbInfo->address);
        free(m_dbInfo->username);
        free(m_dbInfo->password);
        if (NULL != m_dbInfo->ca_cert) {
            free(m_dbInfo->ca_cert);
        }
        free(m_dbInfo->db_name);

        free(m_dbInfo);
        m_dbInfo = NULL;
    }
} /* void vms_close(void) */

bool vms_open(char *address, uint16_t port, char *username, char *password, char *ca_cert, char *db_name) {
    bool success = true;
    int32_t rc;

    if (NULL == db_name) {
        success = false;
        syslog(LOG_ERR, "%s:%d db_name must be specified to open QS/VMS connection",
                __FUNCTION__, __LINE__);
    } else /* !(NULL == db_name) */ {
        if (NULL == m_dbInfo) {
            m_dbInfo = (VmsDbServerInfo_t*) malloc(sizeof(VmsDbServerInfo_t));

            if (NULL == address) {
                /* Use a default server address */
                m_dbInfo->address = strdup("localhost");
            } else {
                m_dbInfo->address = strdup(address);
            }

            if (0 == port) {
                /* Use the default MySQL listening port */
                m_dbInfo->port = 3306;
            } else {
                m_dbInfo->port = port;
            }

            if (NULL == username) {
                /* Use a default username
                 * TODO: storing usernames plain-text in a library is not ideal. */
                m_dbInfo->username = strdup("root");
            } else {
                m_dbInfo->username = strdup(username);
            }

            if (NULL == password) {
                /* Use a default password
                 * TODO: storing passwords plain-text in a library is a bad idea. */
                m_dbInfo->password = strdup("root");
            } else {
                m_dbInfo->password = strdup(password);
            }

            if (NULL == ca_cert) {
                /* Default to not using encryption */
                m_dbInfo->ca_cert = NULL;
            } else {
                m_dbInfo->ca_cert = strdup(ca_cert);
            }

            /* The DB name must be specified */
            m_dbInfo->db_name = strdup(db_name);
        } /* if (NULL == m_dbInfo) */
    } /* else !(NULL == db_name) */

    if (true == success) {
        /* If the VMS DB connection hasn't been created yet, create it now. */
        rc = pthread_once(&m_dbOnce, vms_init);
        if (0 != rc) {
            success = false;
            syslog(LOG_ERR, "%s:%d error initializing DB connection (%d:%s)",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }

        /* If m_dbData is still NULL, return failure. */
        if (NULL == m_dbData) {
            success = false;
        }
    }

    return success;
} /* bool vms_open(char *address, uint16_t port, char *username, char *password, char *ca_cert, char *db_name) */

bool vms_param_update(uint32_t id, double val) {
    bool success = false;
    MYSQL_BIND bind[2];

    if (NULL != m_dbData) {
        if (NULL != m_dbData->param_update_stmt) {
            memset(bind, 0, sizeof(bind));

            bind[0].buffer_type = MYSQL_TYPE_LONG;
            bind[0].buffer = (char*)&id;
            bind[0].is_null = 0;
            bind[0].length = 0;

            bind[1].buffer_type = MYSQL_TYPE_DOUBLE;
            bind[1].buffer = (char*)&val;
            bind[1].is_null = 0;
            bind[1].length = 0;

            if (0 != mysql_stmt_bind_param(m_dbData->param_update_stmt, bind)) {
                syslog(LOG_ERR, "%s:%d unable to bind (%u, %f) values to update parameter MySQL statement (%s)",
                       __FUNCTION__, __LINE__, id, val, mysql_error(m_dbData->mysql));
            } else {
                if (0 != mysql_stmt_execute(m_dbData->param_update_stmt)) {
                    syslog(LOG_ERR, "%s:%d unable to execute update parameter MySQL statement for params (%u, %f) (%s)",
                           __FUNCTION__, __LINE__, id, val, mysql_error(m_dbData->mysql));
                } else {
                    success = true;
                }
            }
        } /* if (NULL != m_dbData->param_update_stmt) */
    } /* if (NULL != m_dbData) */

    return success;
} /* bool vms_param_update(uint32_t id, double val) */

bool vms_increment_session(void) {
    bool success = false;

    if (NULL != m_dbData) {
        if (NULL != m_dbData->incr_session_stmt) {
            if (0 != mysql_stmt_execute(m_dbData->incr_session_stmt)) {
                syslog(LOG_ERR, "%s:%d unable to execute update session MySQL statement for status (%s)",
                       __FUNCTION__, __LINE__, mysql_error(m_dbData->mysql));
            } else {
                success = true;
            }
        } /* if (NULL != m_dbData->incr_session_stmt) */
    } /* if (NULL != m_dbData) */

    return success;
} /* bool vms_increment_session(void) */

bool vms_status_update(char *message) {
    bool success = false;
    MYSQL_BIND bind[1];

    if (NULL != m_dbData) {
        if (NULL != m_dbData->status_update_stmt) {
            memset(bind, 0, sizeof(bind));

            bind[0].buffer_type = MYSQL_TYPE_STRING;
            bind[0].buffer = message;
            bind[0].buffer_length = strlen(message);
            bind[0].is_null = 0;
            bind[0].length = 0;

            if (0 != mysql_stmt_bind_param(m_dbData->status_update_stmt, bind)) {
                syslog(LOG_ERR, "%s:%d unable to bind (%s) values to update status MySQL statement (%s)",
                       __FUNCTION__, __LINE__, message, mysql_error(m_dbData->mysql));
            } else {
                if (0 != mysql_stmt_execute(m_dbData->status_update_stmt)) {
                    syslog(LOG_ERR, "%s:%d unable to execute update status MySQL statement for status (%s) (%s)",
                           __FUNCTION__, __LINE__, message, mysql_error(m_dbData->mysql));
                } else {
                    success = true;
                }
            }
        } /* if (NULL != m_dbData->status_update_stmt) */
    } /* if (NULL != m_dbData) */

    return success;
} /* bool vms_status_update(char *message) */

bool vms_set_vm_state(char *name, VmState_t state) {
    bool success = false;
    MYSQL_BIND bind[3];

    if ((NULL != m_dbData) && (NULL != m_dbData->app_state_update_stmt)) {
        if (ARRAY_SIZE(m_stateMap) > state) {
            /* Don't allow QS_VMS_VM_UNKNOWN to be reported. */
            if (QS_VMS_VM_UNKNOWN != state) {
                memset(bind, 0, sizeof(bind));

                bind[0].buffer_type = MYSQL_TYPE_LONG;
                bind[0].buffer = (char*)&m_stateMap[state].state_value;
                bind[0].is_null = 0;
                bind[0].length = 0;

                bind[1].buffer_type = MYSQL_TYPE_STRING;
                bind[1].buffer = m_stateMap[state].state_string;
                bind[1].buffer_length = strlen(m_stateMap[state].state_string);
                bind[1].is_null = 0;
                bind[1].length = 0;

                bind[2].buffer_type = MYSQL_TYPE_STRING;
                bind[2].buffer = name;
                bind[2].buffer_length = strlen(name);
                bind[2].is_null = 0;
                bind[2].length = 0;

                if (0 != mysql_stmt_bind_param(m_dbData->app_state_update_stmt, bind)) {
                    syslog(LOG_ERR, "%s:%d unable to bind name %s, state %u (%u/%s) values to update status MySQL statement (%s)",
                           __FUNCTION__, __LINE__, name, state, m_stateMap[state].state_value, m_stateMap[state].state_string, mysql_error(m_dbData->mysql));
                } else {
                    if (0 != mysql_stmt_execute(m_dbData->app_state_update_stmt)) {
                        syslog(LOG_ERR, "%s:%d unable to execute update status MySQL statement for name %s, state %u (%u/%s) (%s)",
                               __FUNCTION__, __LINE__, name, state, m_stateMap[state].state_value, m_stateMap[state].state_string, mysql_error(m_dbData->mysql));
                    } else {
                        success = true;
                    }
                }
            } /* if (QS_VMS_VM_UNKNOWN != state) */
        } else { /* ! (ARRAY_SIZE(m_stateMap) > state) */
            syslog(LOG_ERR, "%s:%d invalid state %u specified for VM %s",
                   __FUNCTION__, __LINE__, state, name);
        }
    } else { /* !  ((NULL != m_dbData) && (NULL != m_dbData->...)) */
        syslog(LOG_ERR, "%s:%d VMS connection not initialized",
               __FUNCTION__, __LINE__);
    }

    return success;
} /* bool vms_set_vm_state(char *name, VmState_t state) */

static void vms_init(void) {
    bool success = true;
    MYSQL *ret;

    m_dbData = (VmsDbConn_t*) malloc(sizeof(VmsDbConn_t));
    memset(m_dbData, 0, sizeof(VmsDbConn_t));

    /* There is no need to verify that m_dbInfo is not NULL because this 
     * function is only called once m_dbInfo has been allocated */
    if (NULL == m_dbData) {
        success = false;
        syslog(LOG_ERR, "%s:%d unable to allocate memory for DB connection",
               __FUNCTION__, __LINE__);
    } else /* !(NULL == m_dbData) */ {
        /* Initialize MySQL and connect to the remote DB. */
        m_dbData->mysql = mysql_init(NULL);
        if (NULL == m_dbData->mysql) {
            syslog(LOG_ERR, "%s:%d insufficent memory to initialize MySQL library",
                   __FUNCTION__, __LINE__);
            success = false;
        }

        if (success) {
            /* Secure the database connection */
            mysql_ssl_set(m_dbData->mysql, NULL, NULL, m_dbInfo->ca_cert, NULL, NULL);

            ret = mysql_real_connect(
                m_dbData->mysql, m_dbInfo->address, m_dbInfo->username,
                m_dbInfo->password, m_dbInfo->db_name, m_dbInfo->port, NULL, 0);
            if (ret != m_dbData->mysql) {
                syslog(LOG_ERR, "%s:%d unable to connect to MySQL db %s@%s:%u (%s)",
                       __FUNCTION__, __LINE__,
                       m_dbInfo->db_name, m_dbInfo->address, m_dbInfo->port,
                       mysql_error(m_dbData->mysql));
                success = false;
            }
        }

        /* Initialize the prepared statements */
        if (success) {
            m_dbData->incr_session_stmt = mysql_stmt_init(m_dbData->mysql);
            if (NULL == m_dbData->incr_session_stmt) {
                syslog(LOG_ERR, "%s:%d unable to initialize to MySQL prepared statement (%s)",
                       __FUNCTION__, __LINE__, mysql_error(m_dbData->mysql));
                success = false;
            }
        }

        if (success) {
#define INCR_SESSION_STMT_STR "INSERT INTO `stepSATdb_Flight`.`Recording_Sessions` (`recording_session_id`) SELECT MAX(`recording_session_id`) + 1 FROM `stepSATdb_Flight`.`Recording_Sessions`"
            if (0 != mysql_stmt_prepare(m_dbData->incr_session_stmt,
                                        INCR_SESSION_STMT_STR, strlen(INCR_SESSION_STMT_STR))) {
                syslog(LOG_ERR, "%s:%d unable to prepare session increment MySQL statement (%s)",
                       __FUNCTION__, __LINE__, mysql_error(m_dbData->mysql));
                success = false;
            }
        }

        if (success) {
            m_dbData->param_update_stmt = mysql_stmt_init(m_dbData->mysql);
            if (NULL == m_dbData->param_update_stmt) {
                syslog(LOG_ERR, "%s:%d unable to initialize to MySQL prepared statement (%s)",
                       __FUNCTION__, __LINE__, mysql_error(m_dbData->mysql));
                success = false;
            }
        }

        if (success) {
#define PARAM_UPDATE_STMT_STR "INSERT INTO `stepSATdb_Flight`.`Flight_Data` (`parameter_id`, `time_stamp`, `parameter_value`, `Recording_Sessions_recording_session_id` ) VALUES (?, (NOW() + 0), ?, (SELECT MAX(`recording_session_id`) FROM `stepSATdb_Flight`.`Recording_Sessions`))"
            if (0 != mysql_stmt_prepare(m_dbData->param_update_stmt,
                                        PARAM_UPDATE_STMT_STR, strlen(PARAM_UPDATE_STMT_STR))) {
                syslog(LOG_ERR, "%s:%d unable to prepare update parameter MySQL statement (%s)",
                       __FUNCTION__, __LINE__, mysql_error(m_dbData->mysql));
                success = false;
            }
        }

        if (success) {
            m_dbData->status_update_stmt = mysql_stmt_init(m_dbData->mysql);
            if (NULL == m_dbData->status_update_stmt) {
                syslog(LOG_ERR, "%s:%d unable to initialize to MySQL prepared statement (%s)",
                       __FUNCTION__, __LINE__, mysql_error(m_dbData->mysql));
                success = false;
            }
        }

        if (success) {
#define STATUS_UPDATE_STMT_STR "INSERT INTO `stepSATdb_Flight`.`System_Messages` (`event_time`, `sysmsg`, `Recording_Sessions_recording_session_id`) VALUES ((NOW() + 0), ?, (SELECT MAX(`recording_session_id`) FROM `stepSATdb_Flight`.`Recording_Sessions`))"
            if (0 != mysql_stmt_prepare(m_dbData->status_update_stmt,
                                        STATUS_UPDATE_STMT_STR, strlen(STATUS_UPDATE_STMT_STR))) {
                syslog(LOG_ERR, "%s:%d unable to prepare update status MySQL statement (%s)",
                       __FUNCTION__, __LINE__, mysql_error(m_dbData->mysql));
                success = false;
            }
        }

        if (success) {
            m_dbData->app_state_update_stmt = mysql_stmt_init(m_dbData->mysql);
            if (NULL == m_dbData->app_state_update_stmt ) {
                syslog(LOG_ERR, "%s:%d unable to initialize to MySQL prepared statement (%s)",
                       __FUNCTION__, __LINE__, mysql_error(m_dbData->mysql));
                success = false;
            }
        }

        if (success) {
#define APP_STATE_UPDATE_STMT_STR "UPDATE `stepSATdb_Flight`.`System_Applications` SET `System_Applications`.`application_state`=?, `System_Applications`.`application_status`=? WHERE `System_Applications`.`Configuration_Parts_part_key`=?"
            if (0 != mysql_stmt_prepare(m_dbData->app_state_update_stmt,
                                        APP_STATE_UPDATE_STMT_STR, strlen(APP_STATE_UPDATE_STMT_STR))) {
                syslog(LOG_ERR, "%s:%d unable to prepare update status MySQL statement (%s)",
                       __FUNCTION__, __LINE__, mysql_error(m_dbData->mysql));
                success = false;
            }
        }
        /* If any of these initialization steps failed, deallocate the
         * resources and close the connection */
        if (!success) {
            vms_close();
        }
    } /* else !(NULL == m_dbData) */
} /* static void vms_init(void) */

