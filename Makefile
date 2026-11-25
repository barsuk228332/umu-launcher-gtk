PYTHON ?= python3
PREFIX ?= /usr/local

APP_HOME ?= $(HOME)/.local/share/umulauncher
APP_DIR ?= $(APP_HOME)/app
BIN_DIR ?= $(HOME)/.local/bin
DESKTOP_DIR ?= $(HOME)/.local/share/applications

.PHONY: all run test i18n pot install uninstall clean

all: i18n

run:
	$(PYTHON) -m umulauncher

test:
	$(PYTHON) -m unittest discover -s tests -v

pot:
	xgettext --language=Python --keyword=_ --keyword=ngettext:1,2 \
		--add-comments=TRANSLATORS: --from-code=UTF-8 \
		--package-name=umulauncher --output=po/umulauncher.pot \
		umulauncher/core/*.py umulauncher/ui/*.py umulauncher/__main__.py

i18n:
	@for lang in ru en; do \
		mkdir -p umulauncher/locale/$$lang/LC_MESSAGES; \
		if [ -f po/$$lang.po ]; then \
			msgfmt --check --output-file=umulauncher/locale/$$lang/LC_MESSAGES/umulauncher.mo po/$$lang.po; \
		fi; \
	done

# Install without pip: copy the package and create a small wrapper in ~/.local/bin.
install: i18n
	rm -rf "$(APP_DIR)"
	mkdir -p "$(APP_DIR)" "$(BIN_DIR)" "$(DESKTOP_DIR)"
	cp -r umulauncher pyproject.toml "$(APP_DIR)/"
	find "$(APP_DIR)" -name '__pycache__' -type d -prune -exec rm -rf {} +
	printf '#!/bin/sh\nexport PYTHONPATH="%s"\nexec %s -m umulauncher "$$@"\n' "$(APP_DIR)" "$(PYTHON)" > "$(BIN_DIR)/umulauncher"
	chmod 755 "$(BIN_DIR)/umulauncher"
	install -m 644 data/io.github.umulauncher.Umulauncher.desktop \
		"$(DESKTOP_DIR)/io.github.umulauncher.Umulauncher.desktop"
	sed -i 's|^Exec=umulauncher$$|Exec=$(BIN_DIR)/umulauncher|' \
		"$(DESKTOP_DIR)/io.github.umulauncher.Umulauncher.desktop"
	@echo "Installed: $(BIN_DIR)/umulauncher"
	@echo "Make sure $(BIN_DIR) is in PATH, then run: umulauncher"

uninstall:
	rm -f "$(BIN_DIR)/umulauncher"
	rm -f "$(DESKTOP_DIR)/io.github.umulauncher.Umulauncher.desktop"
	rm -rf "$(APP_DIR)"
	@echo "Removed umulauncher (library and settings are kept in ~/.local/share/umulauncher and ~/.config/umulauncher)"

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf build dist *.egg-info
