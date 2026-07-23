import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState, type ReactNode } from "react";
import { FaStethoscope } from "react-icons/fa";

type Status = "enabled" | "disabled" | "unknown";

interface DiagnosticData {
  currentGame: string;
  graphics: {
    api: string;
    renderer: string;
    presentation: string;
    hdr: Status;
    frameGeneration: string;
    frameGenerationStatus: Status;
  };
  runtime: {
    process: string;
    executable: string;
    pid: string;
    parent: string;
    launchCommand: string;
    proton: string;
    engine: string;
  };
  performance: { gpuBound: Status; cpuBound: Status; vram: string };
}

const getDiagnostics = callable<[], DiagnosticData>("get_diagnostics");

function StatusValue({ status, label }: { status: Status; label?: string }) {
  if (status === "unknown") return <span>{label ?? "Not detected"}</span>;
  const enabled = status === "enabled";
  return (
    <span style={{ color: enabled ? "#a7e66f" : "#f08080" }}>
      {enabled ? "✔" : "✖"}
      {label ? ` ${label}` : ""}
    </span>
  );
}

function DiagnosticRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <PanelSectionRow>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          width: "100%",
          gap: "16px",
        }}
      >
        <span style={{ opacity: 0.7 }}>{label}</span>
        <span style={{ textAlign: "right" }}>{value}</span>
      </div>
    </PanelSectionRow>
  );
}

function Content() {
  const [diagnostics, setDiagnostics] = useState<DiagnosticData>();
  const [error, setError] = useState<string>();
  const [isLoading, setIsLoading] = useState(true);
  const refresh = async () => {
    setIsLoading(true);
    setError(undefined);
    try {
      setDiagnostics(await getDiagnostics());
    } catch (reason) {
      console.error("Unable to load diagnostics", reason);
      setError("Unable to read runtime data.");
    } finally {
      setIsLoading(false);
    }
  };
  useEffect(() => {
    void refresh();
  }, []);

  if (!diagnostics)
    return (
      <PanelSection title="🎮 Game Diagnostic">
        <PanelSectionRow>{error ?? "Reading runtime data…"}</PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void refresh()}>
            {isLoading ? "Refreshing…" : "Retry"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    );
  const { currentGame, graphics, runtime, performance } = diagnostics;

  if (currentGame == "Not detected")
    return (
      <PanelSection title="🎮 Game Diagnostic">
        <DiagnosticRow label="Current Game" value="No game running" />
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void refresh()}>
            {isLoading ? "Refreshing…" : "Refresh diagnostics"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    );
  return (
    <>
      <PanelSection title="🎮 Game Diagnostic">
        <DiagnosticRow label="Current Game" value={currentGame} />
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void refresh()}>
            {isLoading ? "Refreshing…" : "Refresh diagnostics"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Graphics">
        <DiagnosticRow label="API" value={graphics.api} />
        <DiagnosticRow label="Renderer" value={graphics.renderer} />
        <DiagnosticRow label="Presentation" value={graphics.presentation} />
        <DiagnosticRow
          label="HDR"
          value={
            <StatusValue
              status={graphics.hdr}
              label={graphics.hdr === "enabled" ? "Enabled" : undefined}
            />
          }
        />
        <DiagnosticRow
          label="Frame Generation"
          value={
            <StatusValue
              status={graphics.frameGenerationStatus}
              label={
                graphics.frameGenerationStatus === "enabled"
                  ? graphics.frameGeneration
                  : undefined
              }
            />
          }
        />
      </PanelSection>
      <PanelSection title="Runtime">
        <DiagnosticRow label="Process" value={runtime.process} />
        <DiagnosticRow label="Executable" value={runtime.executable} />
        <DiagnosticRow label="PID" value={runtime.pid} />
        <DiagnosticRow label="Parent" value={runtime.parent} />
        <DiagnosticRow label="Launch Command" value={runtime.launchCommand} />
        <DiagnosticRow label="Proton" value={runtime.proton} />
        <DiagnosticRow label="Engine" value={runtime.engine} />
      </PanelSection>
      <PanelSection title="Performance">
        <DiagnosticRow
          label="GPU Bound"
          value={<StatusValue status={performance.gpuBound} />}
        />
        <DiagnosticRow
          label="CPU Bound"
          value={<StatusValue status={performance.cpuBound} />}
        />
        <DiagnosticRow label="VRAM" value={performance.vram} />
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "Game Diagnostic",
  titleView: <div className={staticClasses.Title}>Game Diagnostic</div>,
  content: <Content />,
  icon: <FaStethoscope />,
}));
