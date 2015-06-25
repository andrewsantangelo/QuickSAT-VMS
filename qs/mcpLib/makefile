CC          := gcc
AR          := ar
AS          := as
LINKER      := ld
RANLIB      := ranlib
SIZE        := size
OBJCOPY     := objcopy
OBJDUMP     := objdump

VER_MAJOR   := 0
VER_MINOR   := 5.0
LIBNAME     := mcp
TARGET      := lib$(LIBNAME).so.$(VER_MAJOR).$(VER_MINOR)
SYS         := $(shell $(CC) -dumpmachine)

ASMDIR      :=
LIBDIR      := lib
SRCDIR      := src
INCDIR      := src ../include
BUILDDIR    := build
LIBS        := rt
DYNLIBS     := sql
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
endif

vpath %.s $(ASMDIR)
vpath %.c $(SRCDIR)
vpath %.o $(BUILDDIR)
vpath %.a $(BUILDDIR) ../lib
vpath %.so $(BUILDDIR) ../lib

.PHONY: all debug clean objdump
.DEFAULT: all

#all: CFLAGS += $(OPTFLAGS)
all: CFLAGS += $(DEBUGFLAGS)
all: $(BUILDDIR)/$(TARGET)

debug: CPPFLAGS += -DDEBUG
debug: CFLAGS += $(DEBUGFLAGS)
debug: $(BUILDDIR)/$(TARGET)

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

# Build a static library
$(BUILDDIR)/lib$(LIBNAME).a: $(LIBDEPS) $(OBJECTS) $(MAKEFILE_LIST)
	$(AR) rcs $@ $(OBJECTS)

# Build a shared library
$(BUILDDIR)/lib$(LIBNAME).so.$(VER_MAJOR).$(VER_MINOR): $(LIBDEPS) $(OBJECTS) $(MAKEFILE_LIST)
	$(CC) -shared -Wl,-soname,lib$(LIBNAME).so.$(VER_MAJOR) -o $@ $(OBJECTS) $(LDFLAGS)

# Lastly, a catchall rule for building executables
#$(BUILDDIR)/$(TARGET): $(LIBDEPS) $(LIBARCHIVES) $(OBJECTS) $(MAKEFILE_LIST)
#	$(CC) -o $@ $(OBJECTS) $(DEBUGFLAGS) $(LDFLAGS)

