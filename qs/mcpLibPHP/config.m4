CC=gcc
PHP_ARG_ENABLE(mcpphp, whether to enable MCP data access support,
[ --enable-mcpphp   Enable MCP support])
if test "$PHP_MCPPHP" = "yes"; then
  AC_DEFINE(HAVE_MCPPHP, 1, [Whether you have MCP])

  MCPPHP_INCDIR="../include"
  MCPPHP_LIBDIR="../lib"

  dnl CFLAGS="$CFLAGS -pthread"

  PHP_ADD_INCLUDE($MCPPHP_INCDIR)
  PHP_ADD_LIBPATH($MCPPHP_LIBDIR)

  dnl Manually create the libline to process
  dnl MCPPHP_LIBLINE="-L../lib -lmcp -lsql -ldl -lrt"
  dnl PHP_EVAL_LIBLINE($MCPPHP_LIBLINE, MCPPHP_SHARED_LIBADD)

  PHP_CHECK_LIBRARY(dl, dlopen,
  [
    dnl PHP_ADD_LIBRARY(dl, MCPPHP_SHARED_LIBADD)
    PHP_EVAL_LIBLINE(-ldl, MCPPHP_SHARED_LIBADD)
  ],[
    AC_MSG_ERROR(Could not find dl library)
    dnl ],[
    dnl -L$MCPPHP_LIBDIR
  ])

  PHP_CHECK_LIBRARY(rt, shm_open,
  [
    dnl PHP_ADD_LIBRARY(rt, MCPPHP_SHARED_LIBADD)
    PHP_EVAL_LIBLINE(-lrt, MCPPHP_SHARED_LIBADD)
  ],[
    AC_MSG_ERROR(Could not find rt library)
    dnl ],[
    dnl -L$MCPPHP_LIBDIR
  ])

  PHP_CHECK_LIBRARY(sql, sqlLib_createStmt,
  [
    PHP_ADD_LIBRARY_WITH_PATH(sql, $MCPPHP_LIBDIR, MCPPHP_SHARED_LIBADD)
  ],[
    AC_MSG_ERROR(Could not find SQLite utility library)
    dnl ],[
    dnl -L$MCPPHP_LIBDIR
  ])

  PHP_CHECK_LIBRARY(mcp, mcpLib_open,
  [
    PHP_ADD_LIBRARY_WITH_PATH(mcp, $MCPPHP_LIBDIR, MCPPHP_SHARED_LIBADD)
  ],[
    AC_MSG_ERROR(Could not find MCP library)
    dnl ],[
    dnl -L$MCPPHP_LIBDIR -lsql -ldl -lrt
  ])

  PHP_NEW_EXTENSION(mcpphp, php_mcplib.c, $ext_shared)
  PHP_SUBST(MCPPHP_SHARED_LIBADD)
fi
