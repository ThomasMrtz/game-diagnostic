"""Runtime diagnostics collected from SteamOS process information.

All detection is best-effort: a missing signal is reported as "Not detected"
rather than inferred as a positive result.
"""

import os
import re
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Optional

import decky

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11 (older Decky installations)
    tomllib = None


IGNORED_PROCESS_NAMES = {
    "steam", "steamwebhelper", "pressure-vessel-wrap", "pressure-vessel",
    "pressure-vessel-adverb", "reaper", "proton", "python", "python3",
    "sh", "bash", "gamescope", "timing", "crashpad_handler", "wineserver",
    "explorer.exe", "services.exe", "steam.exe",
}
EMULATORS = ("ryujinx", "yuzu", "dolphin", "rpcs3", "cemu")
NATIVE_OPENGL_LIBRARIES = ("libgl.so", "libopengl.so", "libglx.so", "libglx_mesa.so")
NATIVE_VULKAN_LIBRARIES = ("libvulkan.so",)
WINDOWS_EXECUTABLE_PATTERN = re.compile(
    r'(?:^|\s)(?:"([^"]+\.exe)"|(\S+?\.exe))(?=\s|$)', re.IGNORECASE
)


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


def is_shell_script(process: dict[str, Any]) -> bool:
    """Exclude Steam launch scripts while keeping native Linux binaries."""
    name = process["name"].lower()
    command = process["cmdline"].lower()
    return name.endswith(".sh") or re.search(r"(?:^|\s)\S+\.sh(?:\s|$)", command) is not None


def windows_game_executable(process: dict[str, Any]) -> Optional[str]:
    """Return the Windows game executable passed to Wine or Proton, if any."""
    match = WINDOWS_EXECUTABLE_PATTERN.search(process["cmdline"])
    return next((value for value in match.groups() if value), None) if match else None


def process_executable(process: dict[str, Any]) -> str:
    """Return the game executable rather than a Proton or launcher wrapper."""
    return windows_game_executable(process) or process["cmdline"].split(" ", 1)[0]


def is_windows_game_process(process: dict[str, Any]) -> bool:
    return windows_game_executable(process) is not None


def inherited_steam_app_id(
    processes_by_pid: dict[int, dict[str, Any]], process: dict[str, Any]
) -> Optional[str]:
    """Find the App ID inherited from a Steam shortcut or launcher parent."""
    current: Optional[dict[str, Any]] = process
    visited_pids = set()
    while current and current["pid"] not in visited_pids:
        visited_pids.add(current["pid"])
        app_id = steam_app_id(current)
        if app_id:
            return app_id
        current = processes_by_pid.get(current["ppid"])
    return None


def get_game_title(app_id: Optional[str], process: Optional[dict[str, Any]] = None) -> str:
    if not app_id:
        return "Not detected"

    shortcut_title = get_shortcut_title(app_id, process)
    if shortcut_title:
        return shortcut_title

    for directory in steamapps_directories():
        try:
            manifest = (directory / f"appmanifest_{app_id}.acf").read_text(errors="replace")
        except OSError:
            continue
        match = re.search(r'"name"\s+"([^"]+)"', manifest)
        if match:
            return match.group(1)
    return f"Steam App {app_id}"


def shortcut_app_id(value: Any) -> Optional[int]:
    """Normalise Steam's signed shortcut app ID to its unsigned 32-bit form."""
    try:
        return int(value) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None


def parse_binary_vdf_object(data: bytes, offset: int = 0) -> tuple[dict[str, Any], int]:
    """Parse the small Binary VDF subset used by Steam's shortcuts.vdf file."""
    values: dict[str, Any] = {}
    while offset < len(data):
        value_type = data[offset]
        offset += 1
        if value_type == 0x08:  # KeyValues end marker
            return values, offset

        key_end = data.find(b"\0", offset)
        if key_end < 0:
            raise ValueError("unterminated Binary VDF key")
        key = data[offset:key_end].decode("utf-8", errors="replace")
        offset = key_end + 1

        if value_type == 0x00:  # nested object
            values[key], offset = parse_binary_vdf_object(data, offset)
        elif value_type == 0x01:  # string
            value_end = data.find(b"\0", offset)
            if value_end < 0:
                raise ValueError("unterminated Binary VDF string")
            values[key] = data[offset:value_end].decode("utf-8", errors="replace")
            offset = value_end + 1
        elif value_type == 0x02:  # 32-bit integer
            if offset + 4 > len(data):
                raise ValueError("truncated Binary VDF integer")
            values[key] = struct.unpack_from("<i", data, offset)[0]
            offset += 4
        elif value_type in (0x03, 0x04, 0x06):  # float, pointer, or colour
            if offset + 4 > len(data):
                raise ValueError("truncated Binary VDF value")
            offset += 4
        elif value_type == 0x05:  # UTF-16 string
            value_end = offset
            while value_end + 1 < len(data) and data[value_end:value_end + 2] != b"\0\0":
                value_end += 2
            if value_end + 1 >= len(data):
                raise ValueError("unterminated Binary VDF wide string")
            values[key] = data[offset:value_end].decode("utf-16-le", errors="replace")
            offset = value_end + 2
        elif value_type == 0x07:  # 64-bit integer
            if offset + 8 > len(data):
                raise ValueError("truncated Binary VDF uint64")
            values[key] = struct.unpack_from("<Q", data, offset)[0]
            offset += 8
        else:
            raise ValueError(f"unsupported Binary VDF type {value_type}")
    return values, offset


def vdf_value(values: dict[str, Any], key: str, default: Any = "") -> Any:
    """Read a Binary VDF key case-insensitively."""
    for candidate, value in values.items():
        if candidate.lower() == key.lower():
            return value
    return default


def shortcut_files(process: Optional[dict[str, Any]] = None) -> list[Path]:
    """Return shortcut databases from every locally configured Steam account."""
    steam_roots = {
        directory.parent
        for directory in steamapps_directories()
    }
    homes = (Path(decky.DECKY_USER_HOME), Path.home())
    if process:
        environment = process["env"]
        steam_install = environment.get("STEAM_COMPAT_CLIENT_INSTALL_PATH", "")
        if steam_install:
            steam_roots.add(Path(steam_install))
        process_home = environment.get("HOME", "")
        if process_home:
            homes = (*homes, Path(process_home))
        xdg_data_home = environment.get("XDG_DATA_HOME", "")
        if xdg_data_home:
            steam_roots.add(Path(xdg_data_home) / "Steam")
    steam_roots.update(
        root
        for home in homes
        for root in (
            home / ".local/share/Steam",
            home / ".steam/steam",
            home / ".steam/root",
            home / ".var/app/com.valvesoftware.Steam/data/Steam",
        )
    )

    files = []
    for steam_root in steam_roots:
        userdata = steam_root / "userdata"
        try:
            files.extend(user / "config/shortcuts.vdf" for user in userdata.iterdir() if user.is_dir())
        except OSError:
            continue
    return list(dict.fromkeys(files))


def shortcut_process_match(shortcut: dict[str, Any], process: Optional[dict[str, Any]]) -> bool:
    """Whether a shortcut's configured executable matches the running process."""
    if not process:
        return False

    executable = vdf_value(shortcut, "exe", "")
    if not isinstance(executable, str) or not executable.strip():
        return False
    executable = executable.strip().strip('"').replace("\\", "/").lower()
    signal = " ".join((process["cmdline"], *process["env"].values())).replace("\\", "/").lower()
    if executable in signal:
        return True

    # Proton can run a relative ``./Game.exe`` although Steam stores the
    # absolute path in the shortcut.  Match the filename only when it is a
    # complete command-line token, then require that it identifies one shortcut.
    filename = PureWindowsPath(executable).name or Path(executable).name
    return bool(filename) and re.search(
        rf"(?<![\w.-]){re.escape(filename)}(?![\w.-])", signal
    ) is not None


def get_shortcut_title(
    app_id: str, process: Optional[dict[str, Any]] = None
) -> Optional[str]:
    """Return the display name Steam stores for a matching non-Steam shortcut."""
    target_app_id = shortcut_app_id(app_id)
    if target_app_id is None:
        return None

    # SteamGameId can be a 64-bit CGameID. For shortcuts, the low 24 bits are
    # the shortcut's app ID and bits 24-31 identify it as a shortcut (type 2),
    # so it cannot be compared directly with shortcuts.vdf's signed appid.
    shortcut_game_ids = []
    if process:
        for key in ("SteamGameId", "STEAM_GAME_ID"):
            value = process["env"].get(key, "")
            if value.isdigit():
                shortcut_game_ids.append(int(value))

    process_matches = []
    game_id_matches = []
    for shortcut_file in shortcut_files(process):
        try:
            parsed, _ = parse_binary_vdf_object(shortcut_file.read_bytes())
        except (OSError, ValueError):
            continue

        shortcuts = vdf_value(parsed, "shortcuts", {})
        if not isinstance(shortcuts, dict):
            continue
        for shortcut in shortcuts.values():
            if not isinstance(shortcut, dict):
                continue
            shortcut_id = shortcut_app_id(vdf_value(shortcut, "appid", None))
            title = vdf_value(shortcut, "appname", "")
            if not isinstance(title, str) or not title.strip():
                continue
            title = title.strip()
            if shortcut_id == target_app_id:
                return title
            if any(
                ((game_id >> 24) & 0xFF) == 2
                and shortcut_id is not None
                and (shortcut_id & 0xFFFFFF) == (game_id & 0xFFFFFF)
                for game_id in shortcut_game_ids
            ):
                game_id_matches.append(title)
            if shortcut_process_match(shortcut, process):
                process_matches.append(title)

    # A 24-bit CGameID match and executable-name matches can theoretically
    # collide, so only use either fallback when it identifies one library title.
    for matches in (game_id_matches, process_matches):
        unique_titles = list(dict.fromkeys(matches))
        if len(unique_titles) == 1:
            return unique_titles[0]
    return None


def steamapps_directories() -> list[Path]:
    """Return the default and configured Steam library ``steamapps`` folders."""
    directories = []
    homes = (Path(decky.DECKY_USER_HOME), Path.home())
    for home in homes:
        directories.extend(
            (
                home / ".local/share/Steam/steamapps",
                home / ".steam/steam/steamapps",
            )
        )

    # Steam records each extra library in the libraryfolders VDF.  Its ``path``
    # value is the library root, not the ``steamapps`` directory itself.
    for directory in list(dict.fromkeys(directories)):
        try:
            vdf = (directory / "libraryfolders.vdf").read_text(errors="replace")
        except OSError:
            continue
        for value in re.findall(r'"path"\s+"((?:\\.|[^"\\])*)"', vdf):
            library_root = Path(value.replace(r"\\", "\\"))
            directories.append(
                library_root if library_root.name == "steamapps" else library_root / "steamapps"
            )
    return list(dict.fromkeys(directories))


def proton_paths(
    app_id: Optional[str], process: Optional[dict[str, Any]]
) -> tuple[str, str]:
    """Return the Proton prefix and its Wine user directory.

    Games choose their own subdirectory below this location (for example,
    ``Documents/My Games``), so the Wine user directory is deliberately not
    presented as a title-specific save folder.
    """
    if not app_id:
        return "Not detected", "Not detected"

    compat_data_path = process["env"].get("STEAM_COMPAT_DATA_PATH", "") if process else ""
    if compat_data_path:
        prefix = Path(compat_data_path) / "pfx"
        return str(prefix), str(prefix / "drive_c/users/steamuser")

    candidates = [
        directory / "compatdata" / app_id
        for directory in steamapps_directories()
    ]
    for candidate in candidates:
        if candidate.is_dir():
            prefix = candidate / "pfx"
            return str(prefix), str(prefix / "drive_c/users/steamuser")

    # Keep the path useful even if the prefix cannot be checked (for example,
    # when a game has just started or Steam's library is temporarily offline).
    if candidates:
        prefix = candidates[0] / "pfx"
        return str(prefix), str(prefix / "drive_c/users/steamuser")
    return "Not detected", "Not detected"


def select_game_process(processes: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    processes_by_pid = {process["pid"]: process for process in processes}
    candidates = [
        process
        for process in processes
        if inherited_steam_app_id(processes_by_pid, process) and not is_shell_script(process)
    ]
    # A launcher can legitimately have no non-script child while it is still
    # starting. Retain its script as a temporary anchor instead of reporting no
    # game at all.
    if not candidates:
        candidates = [process for process in processes if steam_app_id(process)]
    if not candidates:
        return None

    def score(process: dict[str, Any]) -> tuple[int, int]:
        name = process["name"].lower()
        command = process["cmdline"].lower()
        executable = Path(process_executable(process)).name.lower()
        is_emulator = any(name == emulator or executable == emulator for emulator in EMULATORS)
        is_ignored = name in IGNORED_PROCESS_NAMES or "steamwebhelper" in command
        # A Windows executable is the strongest available indication of the
        # actual Proton game. PID recency is used only after semantic signals.
        priority = (
            3 if is_windows_game_process(process)
            else 2 if is_emulator
            else 1 if not is_ignored
            else 0
        )
        return priority, process["pid"]

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


def detect_graphics(processes: list[dict[str, Any]], uses_proton: bool) -> tuple[str, str, str]:
    """Identify the renderer from libraries loaded by the game's processes.

    Proton and Steam runtime wrappers can pass VKD3D/DXVK environment variables
    to unrelated children.  Those variables describe launch configuration, not
    necessarily the API used by the current process, so they are deliberately
    not considered here.
    """
    if not processes:
        return "Not detected", "Not detected", "None"

    mapped_libraries = "\n".join(
        read_proc_file(process["pid"], "maps") for process in processes
    ).lower()
    # Proton maps its translation layers as PE DLLs as well as Linux shared
    # objects. Typical entries are .../vkd3d-proton/x64/d3d12.dll and
    # .../dxvk/x64/d3d11.dll, so do not restrict the match to lib*.so names.
    if "vkd3d-proton" in mapped_libraries or "libvkd3d_shader" in mapped_libraries:
        return "Direct3D 12", "VKD3D-Proton", "High"
    if "dxvk" in mapped_libraries:
        return "Direct3D 9/10/11", "DXVK", "High"
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
        return "Direct3D", "WineD3D", "High"
    if uses_proton and d3d12_loaded:
        return "Direct3D 12", "VKD3D-Proton", "High"
    if uses_proton and (
        d3d_9_to_11_loaded
        or "libwined3d" in mapped_libraries
        or "wined3d.dll" in mapped_libraries
    ):
        return "Direct3D 9/10/11", "DXVK", "High"
    # Wine's OpenGL implementation uses opengl32.dll. Check it before the
    # generic WineD3D mapping: Wine can load wined3d as a builtin helper while
    # the game's actual renderer is OpenGL.
    if "opengl32.dll" in mapped_libraries:
        return "OpenGL", "Wine OpenGL", "Medium"
    if "libwined3d" in mapped_libraries or "wined3d.dll" in mapped_libraries:
        return "Direct3D", "WineD3D", "Medium"
    has_opengl = any(library in mapped_libraries for library in NATIVE_OPENGL_LIBRARIES)
    has_vulkan = any(library in mapped_libraries for library in NATIVE_VULKAN_LIBRARIES)
    # A process can map both API families through Steam's runtime, an overlay,
    # or Zink. Mapping alone then cannot identify the API that presents frames.
    if has_opengl and has_vulkan:
        return "Vulkan or OpenGL", "Native", "High"
    if has_vulkan:
        return "Vulkan", "Native", "Medium"
    if has_opengl:
        return "OpenGL", "Native", "Medium"
    return "Not detected", "Not detected", "None"


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




HDR_ENABLED_VALUES = {"1", "true", "yes"}
HDR_SUPPORT_KEYS = ("PROTON_ENABLE_HDR", "DXVK_HDR", "ENABLE_HDR_WSI")


def hdr_enabled(environment: dict[str, str], keys: tuple[str, ...]) -> bool:
    return any(environment.get(key, "").lower() in HDR_ENABLED_VALUES for key in keys)


def detect_hdr_game_support(process: Optional[dict[str, Any]]) -> str:
    """Return HDR support only when the game receives an HDR-capable path.

    These launch markers make Proton/DXVK or the Vulkan WSI advertise HDR to
    the game.  They are evidence that HDR can be used, not evidence that it is
    currently displayed in HDR.
    """
    if not process:
        return "unknown"
    return "enabled" if hdr_enabled(process["env"], HDR_SUPPORT_KEYS) else "unknown"


def hdr_output_enabled(
    processes: list[dict[str, Any]], game: Optional[dict[str, Any]]
) -> bool:
    """Return whether the active game's swapchain is currently HDR."""
    if not game:
        return False

    seen_displays = set()
    for process in [game, *processes]:
        display = process["env"].get("DISPLAY", "")
        if not display or display in seen_displays:
            continue
        seen_displays.add(display)
        app_wants_hdr = gamescope_app_wants_hdr(process)
        if app_wants_hdr is True:
            return True
    return False


def gamescope_app_wants_hdr(process: dict[str, Any]) -> Optional[bool]:
    """Read Gamescope's live HDR swapchain feedback for the active app.

    This property is based on the currently held game commit's colorspace, not
    merely on whether the physical display is in HDR mode.  It is therefore
    only positive while the active app actually presents HDR content.
    """
    display = process["env"].get("DISPLAY", "")
    xprop = shutil.which("xprop")
    if not display or not xprop:
        return None

    environment = os.environ.copy()
    for key in ("DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR"):
        if process["env"].get(key):
            environment[key] = process["env"][key]
    try:
        result = subprocess.run(
            [xprop, "-root", "GAMESCOPE_COLOR_APP_WANTS_HDR_FEEDBACK"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    match = re.search(r"GAMESCOPE_COLOR_APP_WANTS_HDR_FEEDBACK.*=\s*(\d+)", result.stdout)
    return bool(int(match.group(1))) if match else None


def detect_hdr_configuration(
    processes: list[dict[str, Any]], game: Optional[dict[str, Any]], hdr_support: str
) -> str:
    """Return active only for a supported game with HDR output enabled now."""
    if hdr_support != "enabled":
        return "unknown"
    return "enabled" if hdr_output_enabled(processes, game) else "unknown"


def process_label(process: dict[str, Any]) -> str:
    return f"{process['name']} (PID {process['pid']})"


def lsfg_activation_process(game_processes: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return a game process carrying an explicit LSFG activation marker.

    An LSFG Vulkan library mapped into a process is not sufficient evidence: it
    is installed as an implicit layer and can be loaded while frame generation
    is inactive.  The Decky launcher exports ``LSFG_PROCESS`` to the game; the
    other variables cover explicit legacy and v2 launches.
    """
    enabled_values = {"1", "true", "yes"}
    for process in game_processes:
        env = process["env"]
        if env.get("LSFG_PROCESS") or env.get("LSFGVK_PROFILE"):
            return process
        if any(
            env.get(key, "").lower() in enabled_values
            for key in ("ENABLE_LSFG", "LSFG_LEGACY", "LSFGVK_ENV")
        ):
            return process
    return None


def lsfg_layer_process(game_processes: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return the game process in which the LSFG Vulkan layer is actually mapped."""
    for process in game_processes:
        mapped_libraries = read_proc_file(process["pid"], "maps").lower()
        if "liblsfg-vk" in mapped_libraries or "liblsfg_vk" in mapped_libraries:
            return process
    return None


def lsfg_multiplier_from_environment(game_processes: list[dict[str, Any]]) -> Optional[int]:
    """Read explicit legacy and current LSFG environment configuration."""
    for process in game_processes:
        for key in ("LSFG_MULTIPLIER", "LSFGVK_MULTIPLIER"):
            value = process["env"].get(key, "")
            if value.isdigit():
                return int(value)
    return None


def lsfg_config_paths(game_processes: list[dict[str, Any]]) -> list[Path]:
    """Return LSFG config paths, prioritising paths set for the game itself."""
    paths = []
    for process in game_processes:
        for key in ("LSFG_CONFIG", "LSFGVK_CONFIG"):
            value = process["env"].get(key, "")
            if value:
                paths.append(Path(value).expanduser())
    paths.extend(
        home / ".config/lsfg-vk/conf.toml"
        for home in (Path(decky.DECKY_USER_HOME), Path.home())
    )
    return list(dict.fromkeys(paths))


def lsfg_profile_matches_game(profile: dict[str, Any], game_processes: list[dict[str, Any]]) -> bool:
    """Match the v1 ``exe`` and v2 ``active_in`` profile formats."""
    selected_v2_profiles = {
        process["env"].get("LSFGVK_PROFILE", "").lower()
        for process in game_processes
    }
    selected_v2_profiles.discard("")
    profile_name = str(profile.get("name", "")).lower()
    if selected_v2_profiles:
        return profile_name in selected_v2_profiles

    selected_legacy_profiles = {
        process["env"].get("LSFG_PROCESS", "").lower()
        for process in game_processes
    }
    selected_legacy_profiles.discard("")
    if profile_name and profile_name in selected_legacy_profiles:
        return True

    game_names = set()
    for process in game_processes:
        game_names.add(process["name"].lower())
        executable = process["cmdline"].split(" ", 1)[0].strip('"').lower()
        if executable:
            game_names.add(executable)
            game_names.add(Path(executable).name)
        custom_name = process["env"].get("LSFG_PROCESS", "").lower()
        if custom_name:
            game_names.add(custom_name)

    active_in = profile.get("active_in", profile.get("exe", []))
    rules = active_in if isinstance(active_in, list) else [active_in]
    return any(
        isinstance(rule, str)
        and any(name == rule.lower() or name.endswith(rule.lower()) for name in game_names)
        for rule in rules
    )


def lsfg_profiles(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise profile formats used by LSFG-VK and the Decky LSFG plugin."""
    profiles = []
    for key in ("game", "profile"):
        value = config.get(key, [])
        profiles.extend(value if isinstance(value, list) else [value])

    configured_profiles = config.get("profiles", [])
    if isinstance(configured_profiles, list):
        profiles.extend(configured_profiles)
    elif isinstance(configured_profiles, dict):
        for name, profile in configured_profiles.items():
            if isinstance(profile, dict):
                profiles.append({"name": name, **profile})
    return [profile for profile in profiles if isinstance(profile, dict)]


def lsfg_multiplier_from_config(game_processes: list[dict[str, Any]]) -> Optional[int]:
    """Read the multiplier from the matching LSFG v1/v2 TOML profile."""
    if tomllib is None:
        return None

    for config_path in lsfg_config_paths(game_processes):
        try:
            config = tomllib.loads(config_path.read_text(errors="replace"))
        except (OSError, tomllib.TOMLDecodeError):
            continue

        for profile in lsfg_profiles(config):
            if not lsfg_profile_matches_game(profile, game_processes):
                continue
            multiplier = profile.get("multiplier")
            if isinstance(multiplier, int):
                return multiplier

        global_multiplier = config.get("global", {}).get("multiplier")
        if isinstance(global_multiplier, int):
            return global_multiplier
    return None


def lsfg_multiplier(game_processes: list[dict[str, Any]]) -> Optional[int]:
    environment_multiplier = lsfg_multiplier_from_environment(game_processes)
    return (
        environment_multiplier
        if environment_multiplier is not None
        else lsfg_multiplier_from_config(game_processes)
    )


def detect_lsfg(game_processes: list[dict[str, Any]]) -> tuple[str, str, str, str, str]:
    activation_process = lsfg_activation_process(game_processes)
    if not activation_process:
        return (
            "unknown",
            "Not detected",
            "Not detected",
            "Not detected",
            "No explicit LSFG activation marker on the detected game process",
        )

    layer_process = lsfg_layer_process(game_processes)
    activation_label = process_label(activation_process)
    activation_chain = f"LSFG activation marker found in: {activation_label}"
    if not layer_process:
        return (
            "unknown",
            "Not detected",
            activation_label,
            activation_chain,
            "LSFG was requested but its Vulkan layer is not loaded by this game",
        )

    multiplier = lsfg_multiplier(game_processes)
    if multiplier is None or multiplier <= 1:
        return (
            "unknown",
            "Not detected",
            activation_label,
            activation_chain,
            "LSFG was requested but no enabled multiplier could be confirmed",
        )
    return (
        "enabled",
        f"LSFG {multiplier}x",
        process_label(layer_process),
        f"{activation_chain} → LSFG layer loaded in: {process_label(layer_process)}",
        "Explicit LSFG activation marker, loaded Vulkan layer, and multiplier confirmed",
    )


class Plugin:
    async def export_diagnostics(self, report: str) -> dict[str, str]:
        """Save the frontend-generated diagnostic report on the Deck desktop."""
        desktop = Path(decky.DECKY_USER_HOME) / "Desktop"
        desktop.mkdir(parents=True, exist_ok=True)
        filename = f"game-diagnostic-{datetime.now():%Y%m%d-%H%M%S-%f}.txt"
        report_path = desktop / filename
        report_path.write_text(report.rstrip() + "\n", encoding="utf-8")
        decky.logger.info("Diagnostic report exported to %s", report_path)
        return {"path": str(report_path)}

    async def get_diagnostics(self) -> dict[str, Any]:
        processes = all_processes()
        game = select_game_process(processes)
        processes_by_pid = {process["pid"]: process for process in processes}
        app_id = inherited_steam_app_id(processes_by_pid, game) if game else None
        game_processes = game_process_group(processes, game, app_id)
        proton, proton_engine = detect_proton(game)
        proton_prefix, wine_user_directory = proton_paths(app_id, game)
        api, renderer, confidence = detect_graphics(
            game_processes, proton_engine != "Native Linux"
        )
        hdr_support = detect_hdr_game_support(game)
        (
            lsfg_status,
            frame_generation,
            lsfg_process,
            lsfg_chain,
            lsfg_attachment_type,
        ) = detect_lsfg(game_processes)
        decky.logger.debug("Graphics mapping evidence: %s", graphics_map_evidence(game_processes))

        data = {
            "currentGame": get_game_title(app_id, game),
            "appId": app_id or "Not detected",
            "protonPrefix": proton_prefix,
            "wineUserDirectory": wine_user_directory,
            "graphics": {
                "api": api,
                "renderer": renderer,
                "confidence": confidence,
                "hdrSupport": hdr_support,
                "hdrConfiguration": detect_hdr_configuration(processes, game, hdr_support),
                "frameGeneration": frame_generation,
                "frameGenerationStatus": lsfg_status,
                "frameGenerationProcess": lsfg_process,
                "frameGenerationChain": lsfg_chain,
                "frameGenerationAttachment": lsfg_attachment_type,
            },
            "runtime": {
                "process": game["name"] if game else "Not detected",
                "executable": process_executable(game) if game and game["cmdline"] else "Not detected",
                "pid": str(game["pid"]) if game else "Not detected",
                "parent": processes_by_pid.get(game["ppid"], {}).get("name", "Not detected") if game else "Not detected",
                "launchCommand": game["cmdline"] if game and game["cmdline"] else "Not detected",
                "proton": proton,
            },
        }
        decky.logger.debug("Runtime diagnostics refreshed: %s", data)
        return data

    async def _main(self):
        decky.logger.info("Game Diagnostic backend initialized")

    async def _unload(self):
        decky.logger.info("Game Diagnostic backend unloaded")
