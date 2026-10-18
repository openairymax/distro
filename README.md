**Language:** English | [简体中文](README_zh.md)

# AirymaxOS Distro

[![Version](https://img.shields.io/badge/version-0.1.0-5a6b7e)](https://atomgit.com/openairymax/distro)
[![License](https://img.shields.io/badge/license-AGPL--3.0+Apache--2.0-4a90d9)](LICENSE)

> Leaf repository of [agent-linux (AirymaxOS)](https://atomgit.com/openairymax/agent-linux),
> the agent operating system engineering. This repo owns the **OS image
> assembly layer**: everything that turns the AirymaxOS kernel RPM plus the
> openEuler base repository into a bootable, installable distribution.

---

## Overview

**distro** assembles the AirymaxOS distribution image. It pins and combines:

- the AirymaxOS kernel RPM built from the [`kernel`](https://atomgit.com/openairymax/kernel)
  leaf repository (Linux 6.6 baseline, ALK);
- the openEuler 24.03 LTS base repository (hardware driver layer, user-space
 图形栈, toolchain), reusing Euler-verified packages as-is;
- the **UKUI 4.x desktop** (openKylin / openEuler line) as the default system
  desktop, consumed as RPMs — never vendored as source;
- AirymaxOS system-layer components from the other agent-linux leaf
  repositories.

## Initial credentials

Both kickstarts record the initial passwords as SHA-512 crypt hashes per
OS-OPS-009, so an unattended install is login-ready without depending on a
first-boot account creation flow that does not exist yet:

| Account | Initial password | Login boundary |
|---------|------------------|----------------|
| `root` | `Airymax@Root-0.0.3` | Console/SSH takeover; forced rotation at first login |
| `airymax` | `Airymax@User-0.0.3` | `wheel`; lightdm/UKUI desktop account |

`root` runs `chage -d 0` in `%post`, so PAM forces a password change at the
first login. `airymax` is deliberately not expired: how lightdm/ukui-greeter
handles `PAM_NEW_AUTHTOK_REQD` cannot be verified within the 0.0.3 scope, and
expiring it would make the "UKUI desktop is reachable" acceptance criterion
undecidable. The password must therefore be changed right after login. For a
custom build, replace the hashes in the kickstart before injecting the ISO;
never write plaintext.

## Repository layout

```
distro/
├── release/
│   └── os-release                 # Release identity SSoT (VERSION_ID)
├── repo/
│   └── airymax-os.repo            # DNF repo definitions (runtime + lockfile input)
├── specs/
│   ├── macros.airymax             # FHS layout macros (/etc/rpm/macros.airymax)
│   └── airymaxos-release.spec     # Distribution identity package
├── kickstart/
│   ├── airymaxos-minimal.ks       # Minimal unattended install (no desktop)
│   └── airymaxos-workstation.ks   # Installer kickstart (UKUI as default desktop group)
├── comps/
│   ├── comps.dtd                  # Comps 1.0 DTD (local xmllint validation)
│   └── airymaxos-comps.xml        # Package groups: airymax-desktop* → UKUI set
├── lockfile/
│   ├── README.md                  # Freeze policy + freeze-point log
│   ├── gen-lockfile.sh            # Lockfile generator (release workspace only)
│   └── lockfile-openEuler-24.03-LTS-SP2.yaml
├── ostree/
│   ├── README.md                  # rpm-ostree compose workflow
│   └── airymaxos-workstation.treefile
├── desktop/
│   ├── README.md                  # UKUI integration policy (6 rules)
│   ├── airymax-desktop.slice      # Low-interference cgroup slice
│   ├── airymax-desktop-ready.service  # Graphical login chain readiness probe
│   ├── desktop_ready.sh           # lightdm unit + greeter session check
│   ├── 70-airymax-ukui-policy.sh  # Post-install policy script
│   ├── lightdm/                   # lightdm seat policy
│   ├── xinitrc.d/                 # X11 session input method environment
│   ├── autostart/                 # XDG input method autostart entry
│   ├── user@.service.d/           # Bind the session to airymax-desktop.slice
│   ├── wallpaper/                 # Default wallpaper and UKUI registry
│   └── glib-2.0/schemas/          # org.mate.background default override
├── ukui-patches/
│   └── README.md                  # Zero-patch policy (reserved)
├── tools/
│   ├── lint_common.py             # Shared issue type and report format
│   ├── spec_lint.py               # RPM spec static checker (E001-E014)
│   ├── comps_lint.py              # comps semantic checker (C001-C010)
│   ├── ks_lint.py                 # kickstart checker (K001-K015)
│   └── tests/                     # Lint + build-driver regression tests
├── scripts/
│   ├── lib/
│   │   ├── arch.sh                # Host-arch normalisation (shared)
│   │   └── outdir.sh              # Output-directory boundary guard (shared)
│   ├── build-desktop.sh           # Installer medium: offline repo + mkksiso injection
│   ├── build-iso.sh               # Unattended install ISO assembly (mkksiso)
│   ├── build-kernel.sh            # Deterministic kernel archive + RPM entry point
│   ├── build-rpms.sh              # Batch RPM build driver (output outside source tree)
│   └── install-test.sh            # Unattended install x3 (TAP, QEMU)
└── ci/
    ├── README.md                  # Smoke matrix (T1-T4 + X1)
    ├── run-image-ci.sh            # Image gate: five-stage orchestration (minimal/desktop)
    ├── run-lint.sh                # Static gate: shell syntax + spec lint + tests
    └── run-smoke.sh               # Smoke runner (TAP)
```

## Static gates

`ci/run-lint.sh` is the single entry point for static checks and runs with
the Python 3 standard library only (no `rpmbuild`/`mock` required):

- `bash -n` parses every shell entry point under `ci/`, `lockfile/` and
  `scripts/`;
- `tools/spec_lint.py` validates every recipe under `specs/` (tag set,
  `airymaxos-` prefix, `%{?dist}` release, SPDX license, section set,
  source presence, changelog format, version parity with `release/os-release`);
- `tools/comps_lint.py` validates `comps/*.xml` (DOCTYPE, group and
  environment identifiers, package syntax and duplicates, boolean fields,
  environment-to-group references) and cross-checks `kickstart/*.ks`
  selections, including the `@^environment` syntax; when `xmllint` is
  available the file is additionally validated against `comps/comps.dtd`;
- `tools/ks_lint.py` validates `kickstart/*.ks` (section closure, single
  install source, storage layout, accounts that must carry an `--iscrypted`
  SHA-512 password (`--lock` and plaintext are rejected), HTTPS install
  sources, `set -eu` in script sections, `%post --log`, single trailing
  stop command, singleton commands, text/graphical exclusivity, the
  offline `airymaxos-offline` repository (mandatory, with `--baseurl`
  pinned to `file:///run/install/repo/airymax/Packages`), and kernel
  package identity: `airymaxos-kernel` must be installed explicitly while
  upstream `kernel`/`kernel-*` must not be requested);
- `tools/tests/` holds the regression tests for those rules and for the
  build driver contract.

`scripts/install-test.sh --iso PATH [--runs 3]` boots the ISO three times
into fresh qcow2 disks, requires the kickstart `%post` completion marker,
then cold-boots each installed disk and requires a serial boot marker
without a kernel panic. The default marker is `login:`; `--boot-marker`
replaces it, and the desktop image profile uses `AIRYMAX-DESKTOP-READY` to
assert that lightdm and its greeter session are actually up. It emits TAP
14 and exits 77 when the QEMU toolchain is unavailable.

Recipes are validated at commit time; actual RPM builds happen only in the
release workspace, never inside this repository.

`scripts/build-rpms.sh --out DIR` drives the batch build, stages every
`Source`/`Patch` into a private `_topdir`, and optionally publishes a signed
DNF repository (`--repo --stream NAME --gpg-key KEYID`). `DIR` is rejected
unless it resolves outside the source area, so a build cannot pollute the
checkout. Exit codes follow `190-distribution/01-rpm-packaging.md` §8.

`scripts/build-iso.sh --iso SRC --ks FILE --out DIR` assembles the
unattended install medium: it takes the official installer image as the
base, injects the kickstart and serial console arguments through `mkksiso`
(`console=ttyS0,115200` by default), and relabels the volume
(`AIRYMAXOS` by default). Outputs are the ISO, its `.sha256`, and
`iso-manifest.txt`; `--gpg-key` adds a detached signature. The driver then
reads `/ks.cfg` and the BIOS/UEFI boot configuration back out of the
image: the kickstart must match byte for byte, `inst.ks=` must be present,
and every `inst.stage2=` label must equal the final volume label. Any
mismatch fails with `AIRY_EIO` instead of shipping an image that builds but
cannot install. `mkksiso` mounts the source ISO, so physical hosts and CI
run it as root; the output-directory rule is shared with `build-rpms.sh`
through `scripts/lib/outdir.sh`.

`scripts/build-desktop.sh --iso SRC --ks FILE --out DIR --rpms DIR`
assembles the installer medium. It recursively collects the RPM directories
into a self-contained offline repository (`createrepo_c --groupfile
comps/airymaxos-comps.xml`) and refuses to build unless
`airymaxos-release`, `airymaxos-system`, `airymaxos-kernel`, and its
`core`/`modules` subpackages are present. It then writes
`payload/airymax/payload-manifest.txt` and delegates to `build-iso.sh`,
which injects the payload into the ISO root `/airymax` via `--add`. The
minimal and desktop profiles share this driver, and neither needs network
access on the target: the installer fetches packages offline through the
kickstart `repo --baseurl=file:///run/install/repo/airymax/Packages` line.
The minimal profile narrows the required set with repeatable `--require`
flags (kernel trio only), so the desktop closure is not forced onto it.
After assembly the driver reads the payload manifest and `repomd.xml` back
out of the ISO and compares them byte for byte.
`ci/run-image-ci.sh` reuses this path for both profiles and shares the
five-stage TAP gate.

## Kernel isolation boundary (hard rule)

This repository **consumes** kernel artifacts and must never leak into the
kernel repository. The dependency direction is one-way:

- `distro` → consumes: kernel RPM version pins, `[SC]` UAPI headers (packaged);
- `kernel` → knows nothing about `distro`: no spec/comps/kickstart/lockfile
  files are ever added to the kernel leaf repository;
- UKUI patches, if ever required, live in `ukui-patches/` as spec + patch —
  the kernel repository remains untouched;
- Image builds happen **outside** the source area (release workspace), never
  inside this repository; this repo holds recipes and configuration only.

## Branch strategy

This leaf repository develops on **`dev/hubs-01`**, consistent with all
other agent-linux leaf repositories. The aggregating management repo
`agent-linux` stays on `main`.

## Upstream / downstream

### Upstream

- **kernel** — kernel image and modules (consumed as RPM artifacts)
- **services / system / cloudnative** — system-layer components to package
- **openEuler 24.03 LTS** — base repository (drivers, desktop stack, toolchain)
- **openKylin / openEuler UKUI 4.x** — system desktop package set

### Downstream

- End users — install AirymaxOS via the produced installer / image
- Update mechanism — rpm-ostree rebase payloads for baseline transitions

## License

Dual-licensed under **AGPL-3.0-or-later OR Apache-2.0** (SPDX:
`AGPL-3.0-or-later OR Apache-2.0`). See [LICENSE](LICENSE).

Copyright (c) 2025-2026 SPHARX Ltd. All Rights Reserved.
