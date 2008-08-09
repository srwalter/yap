
PREFIX ?= $(HOME)/local

all:
	python setup.py build

install:
	python setup.py install --prefix=$(PREFIX) --install-lib=$(PREFIX)/lib/yap
	mkdir -p $(PREFIX)/bin
	install -m755 yap.bin $(PREFIX)/bin/yap
