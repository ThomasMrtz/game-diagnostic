import { PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { FaStethoscope } from "react-icons/fa";

type Status = "enabled" | "disabled";

interface DiagnosticData {
  currentGame: string;
  graphics: {
    api: string;
    renderer: string;
    presentation: string;
    hdr: Status;
    frameGeneration: string;
  };
  runtime: {
    process: string;
    pid: string;
    proton: string;
    engine: string;
  };
  performance: {
    gpuBound: Status;
    cpuBound: Status;
    vram: string;
  };
}

// Temporary frontend data. Backend phases will replace this object with runtime data.
const diagnosticData: DiagnosticData = {
  currentGame: "Fire Emblem Three Houses",
  graphics: {
    api: "Direct3D 12",
    renderer: "VKD3D-Proton",
    presentation: "Gamescope",
    hdr: "enabled",
    frameGeneration: "LSFG 2x",
  },
  runtime: {
    process: "Ryujinx",
    pid: "2315",
    proton: "GE-Proton10-15",
    engine: "Ryujinx Canary",
  },
  performance: {
    gpuBound: "enabled",
    cpuBound: "disabled",
    vram: "3.4 / 8 GB",
  },
};

function StatusValue({ status, label }: { status: Status; label?: string }) {
  const isEnabled = status === "enabled";

  return (
    <span style={{ color: isEnabled ? "#a7e66f" : "#f08080" }}>
      {isEnabled ? "✔" : "✖"}{label ? ` ${label}` : ""}
    </span>
  );
}

function DiagnosticRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <PanelSectionRow>
      <div style={{ display: "flex", justifyContent: "space-between", width: "100%", gap: "16px" }}>
        <span style={{ opacity: 0.7 }}>{label}</span>
        <span style={{ textAlign: "right" }}>{value}</span>
      </div>
    </PanelSectionRow>
  );
}

function Content() {
  const { currentGame, graphics, runtime, performance } = diagnosticData;

  return (
    <>
      <PanelSection title="🎮 Game Diagnostic">
        <DiagnosticRow label="Current Game" value={currentGame} />
      </PanelSection>

      <PanelSection title="Graphics">
        <DiagnosticRow label="API" value={graphics.api} />
        <DiagnosticRow label="Renderer" value={graphics.renderer} />
        <DiagnosticRow label="Presentation" value={graphics.presentation} />
        <DiagnosticRow label="HDR" value={<StatusValue status={graphics.hdr} label="Enabled" />} />
        <DiagnosticRow
          label="Frame Generation"
          value={<StatusValue status="enabled" label={graphics.frameGeneration} />}
        />
      </PanelSection>

      <PanelSection title="Runtime">
        <DiagnosticRow label="Process" value={runtime.process} />
        <DiagnosticRow label="PID" value={runtime.pid} />
        <DiagnosticRow label="Proton" value={runtime.proton} />
        <DiagnosticRow label="Engine" value={runtime.engine} />
      </PanelSection>

      <PanelSection title="Performance">
        <DiagnosticRow label="GPU Bound" value={<StatusValue status={performance.gpuBound} />} />
        <DiagnosticRow label="CPU Bound" value={<StatusValue status={performance.cpuBound} />} />
        <DiagnosticRow label="VRAM" value={performance.vram} />
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  console.log("Game Diagnostic initialized");

  return {
    name: "Game Diagnostic",
    titleView: <div className={staticClasses.Title}>Game Diagnostic</div>,
    content: <Content />,
    icon: <FaStethoscope />,
    onDismount() {
      console.log("Game Diagnostic unloaded");
    },
  };
});
