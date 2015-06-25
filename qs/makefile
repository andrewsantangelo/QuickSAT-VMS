SYS         := $(shell $(CC) -dumpmachine)

LOCALBIN	:= /usr/local/bin

INSTALLDIR	:=
INCDIR 		:= $(INSTALLDIR)include
LIBDIR 		:= $(INSTALLDIR)lib
BINDIR 		:= $(INSTALLDIR)bin

# The target list specifies the subdirectories that should be built, but also 
# the build order
TARGETS			:= sqlite mcpLib mcp mcpCLI

TGT_SRCDIR		:= src
TGT_BUILDDIR	:= build

include $(TARGETS:%=%/module.mak)

BUILDDEPS		:= $(TARGETS:%=build_%)
INSTALLDEPS		:= $(TARGETS:%=install_%)
CLEANDEPS		:= $(TARGETS:%=clean_%)
UNINSTALLDEPS	:= $(TARGETS:%=uninstall_%)

ifeq (,$(findstring linux, $(SYS)))
# executables have a ".exe" extension when compiled in cygwin
EXE 		:=.exe
endif

.PHONY: all apps_build apps_clean apps_install pyc_clean build install clean uninstall distclean $(BUILDDEPS) $(INSTALLDEPS) $(CLEANDEPS) $(UNINSTALLDEPS) stop_mcp

all: build install apps_build

apps_build:
	@make -C apps/prime
	@make -C apps/sine
	@make -C apps/sine2
	@make -C apps/cos

apps_install: apps/prime/build/primeapp apps/sine/build/sineapp apps/sine2/build/sine2app apps/cos/build/cosapp 
	cp -a apps/prime/build/primeapp /opt/qs/input/
	cp -a apps/sine/build/sineapp /opt/qs/input/
	cp -a apps/sine2/build/sine2app /opt/qs/input/
	cp -a apps/cos/build/cosapp /opt/qs/input/

apps_clean:
	@make -C apps/prime clean
	@make -C apps/sine clean
	@make -C apps/sine2 clean
	@make -C apps/cos clean

pyc_clean:
ifneq ($(wildcard $(BINDIR)/*.pyc), )
	rm -f $(BINDIR)/*.pyc
endif

build: $(BUILDDEPS)

install: $(INSTALLDEPS)

# For now just force remove the dir contents
#@if test -d "$(LIBDIR)"; then rmdir -v $(LIBDIR); fi
distclean: clean uninstall apps_clean pyc_clean
	@if test -d "$(INCDIR)"; then rmdir -v $(INCDIR); fi
	@if test -d "$(LIBDIR)"; then rm -rf -v $(LIBDIR); fi

clean: $(CLEANDEPS)

uninstall: $(UNINSTALLDEPS)

$(INCDIR):
	mkdir -p $@

$(LIBDIR):
	mkdir -p $@

# first param is the filename, second is the module directory, third is the 
# subdirectory where the original file lies, and fourth is the final directory 
# the file is copied to by the install function. 
# 	Ex: $(eval $(call OUTPUT_FILES_RULES_template,sqlite3.h,sqlite,src,$(INCDIR)))
# Older versions of GNU make won't work if there is an '=' after the name of the 
# template being defined.
define OUTPUT_FILES_RULES_template
$(4)/$(1): $(2)/$(3)/$(1) | $(4)
	cp -a $$< $$@
endef

# In cygwin, also copy the library file to the LOCALBIN directory, cause
# otherwise cygwin can't find and load them.
ifeq (,$(findstring linux, $(SYS)))
define OUTPUT_LIB_FILES_RULES_template
$(4)/$(1): $(2)/$(3)/$(1) | $(4)
	cp -a $$< $$@
	cp -a $$< $(LOCALBIN)/$(1)
	cd $(4) && ln -sf $(1) $$(basename $(1))
	cd $(4) && ln -sf $(1) $$(basename $$(basename $(1)))
	cd $(4) && ln -sf $(1) $$(basename $$(basename $$(basename $(1))))
endef
else
define OUTPUT_LIB_FILES_RULES_template
$(4)/$(1): $(2)/$(3)/$(1) | $(4)
	cp -a $$< $$@
	cd $(4) && ln -sf $(1) $$(basename $(1))
	cd $(4) && ln -sf $(1) $$(basename $$(basename $(1)))
	cd $(4) && ln -sf $(1) $$(basename $$(basename $$(basename $(1))))
endef
endif

define MODULE_RULES_template

$(1)_FILES	:= $$(wildcard $(1)/$(TGT_SRCDIR)/*.c $(1)/$(TGT_SRCDIR)/*.h)

build_$(1): $$($(1)_HEADER_DEPS:%=$(INCDIR)/%) $$($(1)_LIB_DEPS:%=$(LIBDIR)/%) $$($(1)_LIBRARIES:%=$(1)/build/%) $$($(1)_EXECUTABLES:%=$(1)/build/%)

install_$(1): $$($(1)_HEADER_FILES:%=$(INCDIR)/%) $$($(1)_LIBRARIES:%=$(LIBDIR)/%) $$($(1)_EXECUTABLES:%=$(BINDIR)/%)

$$($(1)_LIBRARIES:%=$(1)/build/%) $$($(1)_EXECUTABLES:%=$(1)/build/%): $$($(1)_HEADER_DEPS:%=$(INCDIR)/%) $$($(1)_LIB_DEPS:%=$(LIBDIR)/%) $$($(1)_FILES)
	@make -C $(1)

clean_$(1):
	@make -C $(1) clean

uninstall_$(1):
ifneq ($$(wildcard $$($(1)_HEADER_FILES:%=$(INCDIR)/%)), )
	rm -f $$(wildcard $$($(1)_HEADER_FILES:%=$(INCDIR)/%))
endif
ifneq ($$(wildcard $$($(1)_LIBRARIES:%=$(LIBDIR)/%)), )
	rm -f $$(wildcard $$($(1)_LIBRARIES:%=$(LIBDIR)/%))
endif
ifneq ($$(wildcard $$($(1)_EXECUTABLES:%=$(BINDIR)/%)), )
	rm -f $$(wildcard $$($(1)_EXECUTABLES:%=$(BINDIR)/%))
endif

endef

# Add an extra step for copying the MCP daemon executable over, stop it if it is 
# runing.
stop_mcp:
ifneq ($(wildcard /tmp/mcp.pid), )
	-kill -s TERM `cat /tmp/mcp.pid`
	-rm -f /tmp/mcp.pid
endif

install_mcp: stop_mcp

$(foreach tgt,$(TARGETS),$(foreach file,$($(tgt)_HEADER_FILES),$(eval $(call OUTPUT_FILES_RULES_template,$(file),$(tgt),src,$(INCDIR)))))
$(foreach tgt,$(TARGETS),$(foreach file,$($(tgt)_LIBRARIES),$(eval $(call OUTPUT_LIB_FILES_RULES_template,$(file),$(tgt),build,$(LIBDIR)))))
$(foreach tgt,$(TARGETS),$(foreach file,$($(tgt)_EXECUTABLES),$(eval $(call OUTPUT_FILES_RULES_template,$(file),$(tgt),build,$(BINDIR)))))

$(foreach module,$(TARGETS),$(eval $(call MODULE_RULES_template,$(module))))

