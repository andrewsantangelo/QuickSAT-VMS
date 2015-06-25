
#ifndef __SQL_LIB_H__
#define __SQL_LIB_H__

typedef struct SqlStmt_s {
    const char      *cmd;    /* Points to the command string that is used to create the statement */
    sqlite3_stmt    *stmt;
    pthread_mutex_t lock;
} SqlStmt_t;

SqlStmt_t* sqlLib_createStmt(sqlite3 *db, const char *cmd);
void sqlLib_deleteStmt(SqlStmt_t **stmt);

#endif /* __SQL_LIB_H__ */

