# The built files need to be defined for the install and uninstall targets

# The name of this directory 
MODULE := mcpCLI

$(MODULE)_HEADER_DEPS	:= sqlite3.h sqlLib.h mcpLib.h
$(MODULE)_LIB_DEPS 		:= libsql.so.0.5.0 libmcp.so.0.5.0
$(MODULE)_HEADER_FILES 	:=
$(MODULE)_LIBRARIES 	:=
$(MODULE)_EXECUTABLES 	:= mcpCLI

