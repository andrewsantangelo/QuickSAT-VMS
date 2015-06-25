# The built files need to be defined for the install and uninstall targets

# The name of this directory 
MODULE := mcpLib

$(MODULE)_HEADER_DEPS	:= sqlite3.h sqlLib.h
$(MODULE)_LIB_DEPS 		:= libsql.so.0.5.0
$(MODULE)_HEADER_FILES 	:= mcpLib.h
$(MODULE)_LIBRARIES 	:= libmcp.so.0.5.0
$(MODULE)_EXECUTABLES 	:=

