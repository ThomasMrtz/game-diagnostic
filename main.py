"""Runtime diagnostics collected from SteamOS process information.

All detection is best-effort: a missing signal is reported as "Not detected"
rather than inferred as a positive result.
"""

import os
import re
from pathlib import Path
from typing import Any, Optional

import decky


IGNORED_PROCESS_NAMES = {
    "steam", "steamwebhelper", "pressure-vessel-wrap", "pressure-vessel",
    "reaper", "proton", "python", "python3", "sh", "bash", "gamescope",
}
EMULATORS = ("ryujinx", "yuzu", "dolphin", "rpcs3", "cemu")


def read_proc_file(pid: int, name: str) -> str:
    try:
        return Path(f"/proc/{pid}/{name}").read_text(errors="replace")
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return ""


def proc_info(pid: int) -> dict[str, Any]:
    status = read_proc_file(pid, "status")
    parent_match = re.search(r"^PPid:\s+(\d+)$", status, re.MULTILINE)
    cmdline = read_proc_file(pid, "cmdline").replace("\0", " ").strip()
    environ = read_proc_file(pid, "environ").split("\0")
    env = dict(item.split("=", 1) for item in environ if "=" in item)

    return {
        "pid": pid,
        "ppid": int(parent_match.group(1)) if parent_match else 0,
        "name": Path(read_proc_file(pid, "comm").strip()).name,
        "cmdline": cmdline,
        "env": env,
    }


def all_processes() -> list[dict[str, Any]]:
    processes = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return processes
    for entry in entries:
        if entry.name.isdigit():
            info = proc_info(int(entry.name))
            if info["name"]:
                processes.append(info)
    return processes


def steam_app_id(process: dict[str, Any]) -> Optional[str]:
    env = process["env"]
    for key in ("SteamAppId", "SteamGameId", "STEAM_COMPAT_APP_ID"):
        app_id = env.get(key, "")
        if app_id.isdigit() and app_id != "0":
            return app_id
    return None


def get_game_title(app_id: Optional[str]) -> str:
    if not app_id:
        return "Not detected"

    homes = (Path(decky.DECKY_USER_HOME), Path.home())
    suffixes = (
        f".local/share/Steam/steamapps/appmanifest_{app_id}.acf",
        f".steam/steam/steamapps/appmanifest_{app_id}.acf",
    )
    for home in homes:
        for suffix in suffixes:
            try:
                manifest = (home / suffix).read_text(errors="replace")
            except OSError:
                continue
            match = re.search(r'"name"\s+"([^"]+)"', manifest)
            if match:
                return match.group(1)
    return f"Steam App {app_id}"


def select_game_process(processes: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    candidates = [process for process in processes if steam_app_id(process)]
    if not candidates:
        return None

    def score(process: dict[str, Any]) -> tuple[int, int]:
        name = process["name"].lower()
        command = process["cmdline"].lower()
        is_emulator = any(emulator in name or emulator in command for emulator in EMULATORS)
        is_ignored = name in IGNORED_PROCESS_NAMES or "steamwebhelper" in command
        # Prefer an actual emulator/game process. The PID tie-breaker favours the
        # newest child process of a Steam launch.
        return (2 if is_emulator else 0) - (2 if is_ignored else 0), process["pid"]

    return max(candidates, key=score)


def game_process_group(
    processes: list[dict[str, Any]], game: Optional[dict[str, Any]], app_id: Optional[str]
) -> list[dict[str, Any]]:
    """Return the Steam launch process and every descendant that it starts.

    Some Steam runtime wrappers retain SteamAppId while their Wine/game child
    does not. Descendant traversal keeps graphics detection attached to the
    launched title in that case.
    """
    if not game:
        return []

    group = [game]
    group.extend(
        process
        for process in processes
        if process["pid"] != game["pid"] and app_id and steam_app_id(process) == app_id
    )
    known_pids = {process["pid"] for process in group}
    known_pids.add(game["pid"])
    changed = True
    while changed:
        children = [process for process in processes if process["ppid"] in known_pids]
        new_children = [process for process in children if process["pid"] not in known_pids]
        known_pids.update(process["pid"] for process in new_children)
        group.extend(new_children)
        changed = bool(new_children)
    return group


def detect_proton(process: Optional[dict[str, Any]]) -> tuple[str, str]:
    if not process:
        return "Not detected", "Not detected"

    signal = " ".join((process["cmdline"], *process["env"].values()))
    lower_signal = signal.lower()
    ge_match = re.search(r"(?:GE-?Proton|Proton-GE)[^/\\\s]*", signal, re.IGNORECASE)
    proton_match = re.search(r"Proton(?:\s|[-_])?[\w.\-]+", signal, re.IGNORECASE)

    if ge_match:
        return ge_match.group(0), "GE-Proton"
    if proton_match:
        return proton_match.group(0), "Proton"
    if "steamcompat" in lower_signal or "wine" in lower_signal:
        return "Proton / Wine", "Wine"
    return "Native", "Native Linux"


def detect_engine(process: Optional[dict[str, Any]], proton_engine: str) -> str:
    if not process:
        return "Not detected"
    signal = f"{process['name']} {process['cmdline']}".lower()
    for emulator in EMULATORS:
        if emulator in signal:
            return emulator.capitalize() if emulator != "rpcs3" else "RPCS3"
    return proton_engine


def detect_graphics(processes: list[dict[str, Any]], uses_proton: bool) -> tuple[str, str]:
    """Identify the renderer from libraries loaded by the game's processes.

    Proton and Steam runtime wrappers can pass VKD3D/DXVK environment variables
    to unrelated children.  Those variables describe launch configuration, not
    necessarily the API used by the current process, so they are deliberately
    not considered here.
    """
    if not processes:
        return "Not detected", "Not detected"

    mapped_libraries = "\n".join(
        read_proc_file(process["pid"], "maps") for process in processes
    ).lower()
    # Proton maps its translation layers as PE DLLs as well as Linux shared
    # objects. Typical entries are .../vkd3d-proton/x64/d3d12.dll and
    # .../dxvk/x64/d3d11.dll, so do not restrict the match to lib*.so names.
    if "vkd3d-proton" in mapped_libraries or "libvkd3d_shader" in mapped_libraries:
        return "Direct3D 12", "VKD3D-Proton"
    if "dxvk" in mapped_libraries:
        return "Direct3D 9/10/11", "DXVK"
    wined3d_forced = any(
        process["env"].get("PROTON_USE_WINED3D", "").lower() in {"1", "true", "yes"}
        for process in processes
    )
    d3d_9_to_11_loaded = any(
        dll in mapped_libraries for dll in ("d3d9.dll", "d3d10.dll", "d3d11.dll")
    )
    d3d12_loaded = "d3d12.dll" in mapped_libraries
    # Wine often maps wined3d.dll as part of its builtin DLL set even when
    # DXVK handles the game's D3D device. An explicit Proton override is the
    # reliable signal for WineD3D; otherwise D3D 9/10/11 under Proton is DXVK.
    if wined3d_forced:
        return "Direct3D", "WineD3D"
    if uses_proton and d3d12_loaded:
        return "Direct3D 12", "VKD3D-Proton"
    if uses_proton and (
        d3d_9_to_11_loaded
        or "libwined3d" in mapped_libraries
        or "wined3d.dll" in mapped_libraries
    ):
        return "Direct3D 9/10/11", "DXVK"
    # Wine's OpenGL implementation uses opengl32.dll. Check it before the
    # generic WineD3D mapping: Wine can load wined3d as a builtin helper while
    # the game's actual renderer is OpenGL.
    if "opengl32.dll" in mapped_libraries:
        return "OpenGL", "Wine OpenGL"
    if "libwined3d" in mapped_libraries or "wined3d.dll" in mapped_libraries:
        return "Direct3D", "WineD3D"
    has_opengl = any(
        library in mapped_libraries
        for library in ("libgl.so", "libopengl.so", "libglx.so", "libglx_mesa.so")
    )
    has_vulkan = "libvulkan.so" in mapped_libraries
    if has_vulkan and not has_opengl:
        return "Vulkan", "Native Vulkan"
    if has_opengl and not has_vulkan:
        return "OpenGL", "Wine OpenGL" if uses_proton else "Native OpenGL"
    return "Not detected", "Native Vulkan or Native OpenGL"


def graphics_map_evidence(processes: list[dict[str, Any]]) -> list[str]:
    """Return relevant mapping lines for a short, privacy-conscious debug log."""
    keywords = ("vkd3d", "dxvk", "wined3d", "vulkan", "zink", "radeonsi", "iris_dri", "crocus_dri", "d3d9.dll", "d3d10.dll", "d3d11.dll", "d3d12.dll")
    evidence = []
    for process in processes:
        for line in read_proc_file(process["pid"], "maps").splitlines():
            if any(keyword in line.lower() for keyword in keywords):
                evidence.append(f"pid={process['pid']} {line}")
                if len(evidence) == 20:
                    return evidence
    return evidence


def any_process_matches(processes: list[dict[str, Any]], *terms: str) -> bool:
    return any(
        any(term in f"{process['name']} {process['cmdline']}".lower() for term in terms)
        for process in processes
    )


def detect_hdr(process: Optional[dict[str, Any]]) -> str:
    if not process:
        return "unknown"
    keys = ("ENABLE_HDR_WSI", "DXVK_HDR", "GAMESCOPE_HDR", "HDR_OUTPUT")
    enabled = any(process["env"].get(key, "").lower() in {"1", "true", "yes"} for key in keys)
    return "enabled" if enabled else "unknown"


def detect_lsfg(processes: list[dict[str, Any]], process: Optional[dict[str, Any]]) -> tuple[str, str]:
    if not any_process_matches(processes, "lsfg-vk", "lossless scaling"):
        return "unknown", "Not detected"

    signal = " ".join(
        f"{item['cmdline']} {' '.join(item['env'].values())}"
        for item in processes
        if "lsfg" in f"{item['name']} {item['cmdline']}".lower()
    )
    multiplier = re.search(r"(?:multiplier|x)\s*[= ]?\s*([2-9])", signal, re.IGNORECASE)
    return "enabled", f"LSFG {multiplier.group(1) if multiplier else '?'}x"


class Plugin:
    async def get_diagnostics(self) -> dict[str, Any]:
        processes = all_processes()
        game = select_game_process(processes)
        processes_by_pid = {process["pid"]: process for process in processes}
        app_id = steam_app_id(game) if game else None
        game_processes = game_process_group(processes, game, app_id)
        proton, proton_engine = detect_proton(game)
        api, renderer = detect_graphics(game_processes, proton != "Native")
        lsfg_status, frame_generation = detect_lsfg(processes, game)

        decky.logger.debug("Graphics mapping evidence: %s", graphics_map_evidence(game_processes))

        data = {
            "currentGame": get_game_title(app_id),
            "graphics": {
                "api": api,
                "renderer": renderer,
                "presentation": "Gamescope" if any_process_matches(processes, "gamescope") else "Not detected",
                "hdr": detect_hdr(game),
                "frameGeneration": frame_generation,
                "frameGenerationStatus": lsfg_status,
            },
            "runtime": {
                "process": game["name"] if game else "Not detected",
                "executable": game["cmdline"].split(" ", 1)[0] if game and game["cmdline"] else "Not detected",
                "pid": str(game["pid"]) if game else "Not detected",
                "parent": processes_by_pid.get(game["ppid"], {}).get("name", "Not detected") if game else "Not detected",
                "launchCommand": game["cmdline"] if game and game["cmdline"] else "Not detected",
                "proton": proton,
                "engine": detect_engine(game, proton_engine),
            },
            "performance": {
                "gpuBound": "unknown",
                "cpuBound": "unknown",
                "vram": "Not detected",
            },
        }
        decky.logger.debug("Runtime diagnostics refreshed: %s", data)
        return data

    async def _main(self):
        decky.logger.info("Game Diagnostic backend initialized")

    async def _unload(self):
        decky.logger.info("Game Diagnostic backend unloaded")
