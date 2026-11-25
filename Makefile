PYTHON ?= python3
PREFIX ?= /usr/local

.PHONY: all run test i18n pot clean install uninstall

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

install:
	$(PYTHON) -m pip install --user .
	install -Dm644 data/io.github.umulauncher.Umulauncher.desktop \
		$(HOME)/.local/share/applications/io.github.umulauncher.Umulauncher.desktop

uninstall:
	rm -f $(HOME)/.local/share/applications/io.github.umulauncher.Umulauncher.desktop

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf build dist *.egg-info
