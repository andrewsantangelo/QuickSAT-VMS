#ifndef PHP_MCPPHP_H
#define PHP_MCPPHP_H 1
#define PHP_MCPPHP_LIB_VERSION "0.5"
#define PHP_MCPPHP_LIB_EXTNAME "mcpphp"

/* Standard C MCP library functions:
 *  bool mcpLib_open(char *dbfile);
 *  void mcpLib_close(void);
 *  bool mcpLib_getFlightLeg(uint32_t *leg);
 *  bool mcpLib_getOpMode(uint32_t *mode);
 *  bool mcpLib_getMcpState(uint32_t *state);
 *  bool mcpLib_getAllShmStateData(uint32_t *flightLeg, uint32_t *opMode, uint32_t *mcpState);
 *  bool mcpLib_setParam(uint32_t id, double value);
 *  bool mcpLib_getParam(uint32_t id, double *value);
 *  bool mcpLib_getRule(uint32_t id, char **name, char **str);
 */

PHP_MINIT_FUNCTION(mcpphp);
PHP_MSHUTDOWN_FUNCTION(mcpphp);

PHP_FUNCTION(mcp_get_flight_leg);
PHP_FUNCTION(mcp_get_op_mode);
PHP_FUNCTION(mcp_get_state);
PHP_FUNCTION(mcp_get_param);
PHP_FUNCTION(mcp_set_param);

extern zend_module_entry mcpphp_module_entry;
#define phpext_mcpphp_ptr &mcpphp_module_entry

#endif
