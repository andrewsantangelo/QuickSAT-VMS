# The built files need to be defined for the install and uninstall targets

# The name of this directory 
MODULE := sqlite

$(MODULE)_HEADER_DEPS	:=
$(MODULE)_LIB_DEPS 		:=
$(MODULE)_HEADER_FILES 	:= sqlite3.h sqlLib.h
$(MODULE)_LIBRARIES 	:= libsql.so.0.5.0
$(MODULE)_EXECUTABLES 	:=

