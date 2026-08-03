VERSION := $(shell python3 -c 'import json; print(json.load(open("manifest.json"))["version"])')
XPI := build/zotero-agentibility-$(VERSION).xpi

.PHONY: all check xpi clean
all check xpi:
	./check.sh $(XPI)

clean:
	rm -rf build
