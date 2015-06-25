#include <stdint.h>
#include <stdbool.h>
#include "mcpLib.h"

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif
#include "php.h"
#include "php_ini.h"
#include "php_mcplib.h"

static function_entry mcpphp_functions[] = {
    PHP_FE(mcp_get_flight_leg, NULL)
    PHP_FE(mcp_get_op_mode, NULL)
    PHP_FE(mcp_get_state, NULL)
    PHP_FE(mcp_get_param, NULL)
    PHP_FE(mcp_set_param, NULL)
    {NULL, NULL, NULL}
};

zend_module_entry mcpphp_module_entry = {
#if ZEND_MODULE_API_NO >= 20010901
    STANDARD_MODULE_HEADER,
#endif
    PHP_MCPPHP_LIB_EXTNAME,
    mcpphp_functions,
    PHP_MINIT(mcpphp),
    PHP_MSHUTDOWN(mcpphp),
    NULL,
    NULL,
    NULL,
#if ZEND_MODULE_API_NO >= 20010901
    PHP_MCPPHP_LIB_VERSION,
#endif
    STANDARD_MODULE_PROPERTIES
};

#ifdef COMPILE_DL_MCPPHP
ZEND_GET_MODULE(mcpphp)
#endif

PHP_INI_BEGIN()
PHP_INI_ENTRY("mcp.db", "/etc/mcp/mct.db", PHP_INI_SYSTEM, NULL)
PHP_INI_END()

PHP_MINIT_FUNCTION(mcpphp)
{
    REGISTER_INI_ENTRIES();

    return mcpLib_open(INI_STR("mcp.db"));
}

PHP_MSHUTDOWN_FUNCTION(mcpphp)
{
    mcpLib_close();

    UNREGISTER_INI_ENTRIES();

    return SUCCESS;
}

PHP_FUNCTION(mcp_get_flight_leg)
{
    uint32_t val;

    if (true == mcpLib_getFlightLeg(&val))
    {
        RETURN_LONG((int32_t)val);
    }

    RETURN_NULL();
}

PHP_FUNCTION(mcp_get_op_mode)
{
    uint32_t val;

    if (true == mcpLib_getOpMode(&val))
    {
        RETURN_LONG((int32_t)val);
    }

    RETURN_NULL();
}

PHP_FUNCTION(mcp_get_state)
{
    uint32_t val;

    if (true == mcpLib_getMcpState(&val))
    {
        RETURN_LONG((int32_t)val);
    }

    RETURN_NULL();
}

PHP_FUNCTION(mcp_get_param)
{
    unsigned long id;
    double val;

    if (SUCCESS == zend_parse_parameters(ZEND_NUM_ARGS() TSRMLS_CC, "l", &id))
    {
        if (true == mcpLib_getParam(id, &val))
        {
            RETURN_DOUBLE(val);
        }
    }

    RETURN_NULL();
}

PHP_FUNCTION(mcp_set_param)
{
    unsigned long id;
    double val;

    if (SUCCESS == zend_parse_parameters(ZEND_NUM_ARGS() TSRMLS_CC, "ld", &id, &val))
    {
        RETURN_BOOL(mcpLib_setParam(id, val));
    }

    RETURN_NULL();
}

