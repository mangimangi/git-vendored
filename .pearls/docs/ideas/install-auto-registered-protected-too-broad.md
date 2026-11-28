# install's auto-registered vendors get too broad a protected pattern

> Captured: 2026-11-28

## Context

Found while closing `templates/install` coverage to 99% (gv-f492.3, epic gv-f492, commit c3575a7). When a vendor's `install.sh` writes no config, `install_new_vendor` registers the vendor itself and works out `protected` from the manifest. The new tests showed that a manifest with files under `.vendored/pkg/<vendor>/` gives `protected: [".vendored/**"]`. The behaviour was left as it is: that issue allowed defect fixes only, and this one is not clearly a defect.

## Idea

templates/install install_new_vendor derives protected as '.vendored/**' when an auto-registered vendor's manifest has files under .vendored/pkg/<vendor>/ — very broad; check ignores it while a manifest exists, but anything reading 'protected' directly would over-protect. Derive '.vendored/pkg/<vendor>/**' instead.
