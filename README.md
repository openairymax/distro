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

## Repository layout

```
distro/
├── kickstart/        # Installer kickstart files (UKUI as default desktop group)
├── comps/            # Package group definitions (airymax-desktop → UKUI set)
├── lockfile/         # rpm lockfile: openEuler 24.03 SP freeze point + UKUI pins
├── ostree/           # rpm-ostree image recipes (update mechanism)
├── desktop/          # UKUI integration policy: KylinBot disabled, cgroup slice
│                     # isolation, X11-first session, agent entry via Gateway only
├── ukui-patches/     # (reserved) spec + patches for UKUI, if ever needed
└── ci/               # Combined smoke matrix: desktop package set × kernel RPM
```

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

This leaf repository develops on **`develop/hubs-01`**, consistent with all
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
