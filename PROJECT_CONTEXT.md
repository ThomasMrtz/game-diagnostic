# Game Diagnostic

## Overview

Game Diagnostic is a Decky Loader plugin for Steam Deck.

Its goal is to help users quickly understand how a game is running by exposing runtime information that is normally scattered across MangoHud, Proton logs, Gamescope and Linux system tools.

The plugin should focus on diagnostics rather than tweaking settings.

---

# Vision

The plugin should answer questions such as:

- Which graphics API is the game using?
- Is it running through DXVK or VKD3D-Proton?
- Is the game Vulkan or OpenGL?
- Which Proton version is being used?
- Is HDR enabled?
- Is LSFG (Lossless Scaling Frame Generation) active?
- Which process is actually rendering the game?
- Which renderer or emulator is being used?
- Is the game CPU bound or GPU bound?

The objective is to provide useful information in a single place without requiring the user to inspect logs or launch MangoHud.

---

# Initial Features

## Runtime

- Current game name
- Executable name
- Process ID
- Parent process
- Launch command

## Graphics

- Graphics API
  - Direct3D 9
  - Direct3D 10
  - Direct3D 11
  - Direct3D 12
  - Vulkan
  - OpenGL

- Translation layer
  - DXVK
  - VKD3D-Proton
  - Native Vulkan
  - WineD3D
  - Native OpenGL

## Proton

- Proton version
- GE-Proton detection
- Proton launch arguments

## Display

- HDR enabled
- Refresh rate
- Resolution
- Gamescope detection

## LSFG

- Detect if lsfg-vk is active
- Display current frame generation multiplier if possible

---

# Long Term Features

- Detect CPU bottleneck
- Detect GPU bottleneck
- Detect VRAM pressure
- Copy complete diagnostic report
- Export diagnostic as JSON
- Report generator for GitHub or Reddit
- Detect Heroic Launcher
- Detect Steam ROM Manager
- Detect Ryujinx
- Detect RPCS3
- Detect Dolphin
- Detect Cemu

---

# Development Philosophy

Keep the interface simple.

No tuning.

No overclocking.

No performance tweaks.

The plugin is a diagnostic tool.

Every displayed value should be backed by actual runtime information whenever possible.

---

# Development Roadmap

## Phase 1

- Hello World plugin
- Understand Decky architecture
- Frontend only

## Phase 2

- Backend communication
- Static data returned from Python

## Phase 3

- Runtime process detection

## Phase 4

- Graphics API detection

## Phase 5

- Proton detection

## Phase 6

- LSFG detection

## Phase 7

- HDR / Gamescope integration

---

# Tech Stack

Frontend

- React
- TypeScript
- Decky UI components

Backend

- Python

Platform

- SteamOS
- Decky Loader

Development machine

- macOS

Target

- Steam Deck

---

# Notes

The plugin should support both native Linux games and Windows games running through Proton.

Compatibility with Heroic Launcher, Steam ROM Manager and emulators is an important long-term goal.

Whenever possible, information should be detected automatically without requiring user configuration.
