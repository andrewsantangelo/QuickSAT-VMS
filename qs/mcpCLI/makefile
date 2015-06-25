CC          := gcc
AR          := ar
AS          := as
LINKER      := ld
RANLIB      := ranlib
SIZE        := size
OBJCOPY     := objcopy
OBJDUMP     := objdump

TARGET      := mcpCLI
SYS         := $(shell $(CC) -dumpmachine)

MCP_DB_FILE	:= \"$(CURDIR)/../etc/mcp/mct.db\"

ASMDIR      :=
LIBDIR      := lib
SRCDIR      := src
INCDIR      := src ../include
BUILDDIR    := build
LIBS        := dl rt
DYNLIBS     := mcp sql
LIBPATHS    := ../lib

LIBSRC      := $(foreach dir, $(LIBDIR), $(wildcard $(dir)/*.c))
LIBOBJS     := $(patsubst %.c, $(BUILDDIR)/%.o, $(notdir $(LIBSRC)))
LIBARCHIVES := $(LIBOBJS:.o=.a)

EXCLUDESRC  := $(LIBSRC)

SOURCES     := $(filter-out $(EXCLUDESRC), $(foreach dir, $(SRCDIR), $(wildcard $(dir)/*.c)))
OBJECTS     := $(patsubst %.c, $(BUILDDIR)/%.o, $(notdir $(SOURCES)))
DEPS        := $(OBJECTS:.o=.d) $(LIBOBJS:.o=.d)

DEBUGFLAGS  := -g -O0
OPTFLAGS    := -O2

CFLAGS      := -std=gnu99 -Wall -Wnested-externs -Wpointer-arith -Wswitch -Wredundant-decls -Wreturn-type -Wshadow -Wstrict-prototypes -Wextra -Wunused -pedantic -Wno-main -Wuninitialized -Wunused-result -Wno-override-init -Wdeclaration-after-statement -Wmissing-prototypes -Wmissing-declarations -Wundef -fstrict-aliasing -Wstrict-aliasing=3 -Wunused-function -Wformat=2 -Werror
ASFLAGS     :=
CPPFLAGS    := $(INCDIR:%=-I%) -D_GNU_SOURCE
LIBDEPS     := $(DYNLIBS:%=-l%) $(LIBS:%=-l%)

ifneq ($(wildcard $(LIBSRC)), )
# If there are source and object files to create libraries, include the build 
# directory as a location to look for library files
LIBPATHS    += $(BUILDDIR)
endif

# In cygwin shared libraries must be identified by full name
ifneq (,$(findstring cygwin, $(SYS)))
LDFLAGS     := -Wl,-Map=$(BUILDDIR)/$(TARGET).map $(LIBPATHS:%=-Wl,-rpath,'$$ORIGIN/%') $(LIBPATHS:%=-L%) $(DYNLIBS:%=-l:lib%.so) $(LIBS:%=-l%)
else
LDFLAGS     := -Wl,-Map=$(BUILDDIR)/$(TARGET).map $(LIBPATHS:%=-Wl,-rpath,'$$ORIGIN/%') $(LIBPATHS:%=-L%) $(LIBDEPS)
endif

# Add --track-fds=yes to check if there are any FDs left open
MEMCHECK_OPTS := --read-var-info=yes --leak-check=full --track-origins=yes --show-reachable=yes --malloc-fill=B5 --free-fill=4A 

TARGETS     := $(BUILDDIR)/$(TARGET)
MAPS        := $(TARGETS:%=%.map)
OBJDUMPS    := $(TARGETS:%=%.dump)

ifneq (,$(findstring linux, $(SYS)))
# Some additional flags are recommended for linux, but not recognized in cygwin
CFLAGS += -fPIC -pthread
LDFLAGS += -pthread
else
# This flag is set by "-pthread" on linux, but cygwin does not support the 
# "-pthread" option so force _REENTRANT to be defined instead
CPPFLAGS += -D_REENTRANT

# These flags are necessary on cygwin (or any non-linux environment) to
# simulate the standard MCP/Xen environment.
CPPFLAGS += -DMCP_DB_FILE=$(MCP_DB_FILE)
endif

vpath %.s $(ASMDIR)
vpath %.c $(SRCDIR)
vpath %.o $(BUILDDIR)
vpath %.a $(BUILDDIR) ../lib
vpath %.so $(BUILDDIR) ../lib

.PHONY: profile all debug clean objdump
.DEFAULT: all

#all: CFLAGS += $(OPTFLAGS)
all: CFLAGS += $(DEBUGFLAGS)
all: $(BUILDDIR)/$(TARGET)

debug: CPPFLAGS += -DDEBUG
debug: CFLAGS += $(DEBUGFLAGS)
debug: $(BUILDDIR)/$(TARGET)

profile: CPPFLAGS += -DPROFILE
profile: all
	valgrind $(MEMCHECK_OPTS) --suppressions=valgrind.supp --log-file=$(TARGET).profile $(BUILDDIR)/$(TARGET)

clean:
ifneq ($(wildcard $(DEPS)), )
	rm -f $(wildcard $(DEPS))
endif
ifneq ($(wildcard $(LIBOBJS)), )
	rm -f $(wildcard $(LIBOBJS))
endif
ifneq ($(wildcard $(OBJECTS)), )
	rm -f $(wildcard $(OBJECTS))
endif
ifneq ($(wildcard $(LIBARCHIVES)), )
	rm -f $(wildcard $(LIBARCHIVES))
endif
ifneq ($(wildcard $(MAPS)), )
	rm -f $(wildcard $(MAPS))
endif
ifneq ($(wildcard $(OBJDUMPS)), )
	rm -f $(wildcard $(OBJDUMPS))
endif
ifneq ($(wildcard $(TARGET).profile), )
	rm -f $(wildcard $(TARGET).profile)
endif
ifneq ($(wildcard $(TARGETS)), )
	rm -f $(wildcard $(TARGETS))
endif
	@if test -d "$(BUILDDIR)"; then rmdir -v $(BUILDDIR); fi

objdump: $(BUILDDIR)/$(TARGET)
	$(OBJDUMP) -DS $(BUILDDIR)/$(TARGET) > $(BUILDDIR)/$(TARGET).dump

$(BUILDDIR):
	mkdir -p $(BUILDDIR)

-include $(DEPS)

$(BUILDDIR)/%.o: %.s | $(BUILDDIR)
	$(CC) -c $(ASFLAGS) -o $@ $<

# The -MMD flag here causes gcc to generate a .d file automatically which 
# specifies include files that the source file depends on  The sed command 
# appends the main makefile to the dependency list.
$(BUILDDIR)/%.o: %.c | $(BUILDDIR)
	$(CC) -c $(CFLAGS) $(EXTRA_FLAGS) $(CPPFLAGS) -MMD -o $@ $<
	@sed -e '$$s/$$/ $(firstword $(MAKEFILE_LIST))/' -i $(@:%.o=%.d)

$(BUILDDIR)/lib%.a: $(BUILDDIR)/%.o
	$(AR) rcs $@ $<

$(BUILDDIR)/$(TARGET): $(LIBDEPS) $(LIBARCHIVES) $(OBJECTS) $(MAKEFILE_LIST)
	$(CC) -o $@ $(OBJECTS) $(DEBUGFLAGS) $(LDFLAGS)

