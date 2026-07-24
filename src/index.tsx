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
  appId: string;
  protonPrefix: string;
  wineUserDirectory: string;
  graphics: {
    api: string;
    renderer: string;
    confidence: string;
    hdrSupport: Status;
    hdrConfiguration: Status;
    frameGeneration: string;
    frameGenerationStatus: Status;
    frameGenerationProcess: string;
    frameGenerationChain: string;
    frameGenerationAttachment: string;
  };
  runtime: {
    process: string;
    executable: string;
    pid: string;
    parent: string;
    launchCommand: string;
    proton: string;
  };
}

const getDiagnostics = callable<[], DiagnosticData>("get_diagnostics");
const exportDiagnostics = callable<[string], { path: string }>(
  "export_diagnostics",
);

function libraryDisplayName(appId: string): string | undefined {
  if (!/^\d+$/.test(appId)) return undefined;

  // This is Steam's own library record, so display_name is the exact label the
  // user sees in their library for both Steam games and non-Steam shortcuts.
  const numericAppId = Number(appId);
  if (!Number.isSafeInteger(numericAppId)) return undefined;
  const app = window.appStore?.GetAppOverviewByAppID(numericAppId);
  const displayName = app?.display_name?.trim();
  return displayName || undefined;
}

function statusText(status: Status): string {
  if (status === "enabled") return "Enabled";
  if (status === "disabled") return "Disabled";
  return "Not detected";
}

function hdrSupportText(status: Status): string {
  return status === "enabled" ? "Signals detected" : statusText(status);
}

function hdrConfigurationText(status: Status): string {
  return status === "enabled" ? "Active" : statusText(status);
}

function formatDiagnosticReport(diagnostics: DiagnosticData): string {
  const {
    currentGame,
    appId,
    protonPrefix,
    wineUserDirectory,
    graphics,
    runtime,
  } = diagnostics;
  const generatedAt = new Date().toLocaleString();
  const lsfgDetails =
    graphics.frameGenerationStatus === "unknown"
      ? []
      : [
          `LSFG attachment: ${graphics.frameGenerationAttachment}`,
          `LSFG target process: ${graphics.frameGenerationProcess}`,
          `LSFG chain: ${graphics.frameGenerationChain}`,
        ];

  return [
    "GAME DIAGNOSTIC REPORT",
    `Generated: ${generatedAt}`,
    "",
    "GAME",
    `Current game: ${currentGame}`,
    `Steam App ID: ${appId}`,
    `Proton prefix: ${protonPrefix}`,
    `Wine user directory: ${wineUserDirectory}`,
    "",
    "GRAPHICS",
    `API: ${graphics.api}`,
    `Renderer: ${graphics.renderer}`,
    `Detection confidence: ${graphics.confidence}`,
    `HDR support: ${hdrSupportText(graphics.hdrSupport)}`,
    `HDR configuration: ${hdrConfigurationText(graphics.hdrConfiguration)}`,
    `Frame generation: ${graphics.frameGeneration}`,
    ...lsfgDetails,
    "",
    "RUNTIME",
    `Process: ${runtime.process}`,
    `Executable: ${runtime.executable}`,
    `PID: ${runtime.pid}`,
    `Parent: ${runtime.parent}`,
    `Launch command: ${runtime.launchCommand}`,
    `Proton: ${runtime.proton}`,
  ].join("\n");
}

async function copyText(text: string): Promise<void> {
  if (typeof navigator.clipboard?.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (reason) {
      // Steam's embedded browser exposes this API but can reject it because
      // the Decky panel is not a secure, clipboard-permitted context.
      console.debug("Clipboard API unavailable, using legacy copy", reason);
    }
  }

  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.style.position = "fixed";
  textArea.style.left = "-9999px";
  textArea.style.opacity = "0";
  textArea.setAttribute("readonly", "");
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);
  if (!copied) throw new Error("Clipboard is unavailable");
}

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
        <span
          style={{
            textAlign: "right",
            overflowWrap: "anywhere",
            minWidth: 0,
            maxWidth: "65%",
          }}
        >
          {value}
        </span>
      </div>
    </PanelSectionRow>
  );
}

function Content() {
  const [diagnostics, setDiagnostics] = useState<DiagnosticData>();
  const [error, setError] = useState<string>();
  const [isLoading, setIsLoading] = useState(true);
  const [exportStatus, setExportStatus] = useState<string>();
  const [isExporting, setIsExporting] = useState(false);
  const [isCopying, setIsCopying] = useState(false);
  const refresh = async () => {
    setIsLoading(true);
    setError(undefined);
    try {
      const backendDiagnostics = await getDiagnostics();
      setDiagnostics({
        ...backendDiagnostics,
        currentGame:
          libraryDisplayName(backendDiagnostics.appId) ??
          backendDiagnostics.currentGame,
      });
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

  const handleExport = async () => {
    if (!diagnostics) return;
    setIsExporting(true);
    setExportStatus(undefined);
    try {
      const { path } = await exportDiagnostics(
        formatDiagnosticReport(diagnostics),
      );
      setExportStatus(`Report saved to ${path}`);
    } catch (reason) {
      console.error("Unable to export diagnostics", reason);
      setExportStatus("Unable to save the report to the Desktop.");
    } finally {
      setIsExporting(false);
    }
  };

  const handleCopy = async () => {
    if (!diagnostics) return;
    setIsCopying(true);
    setExportStatus(undefined);
    try {
      await copyText(formatDiagnosticReport(diagnostics));
      setExportStatus("Report copied to the clipboard.");
    } catch (reason) {
      console.error("Unable to copy diagnostics", reason);
      setExportStatus("Unable to copy the report to the clipboard.");
    } finally {
      setIsCopying(false);
    }
  };

  const exportActions = diagnostics && (
    <PanelSection title="Export">
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => void handleExport()}>
          {isExporting ? "Saving report…" : "Save report to Desktop"}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => void handleCopy()}>
          {isCopying ? "Copying report…" : "Copy report to clipboard"}
        </ButtonItem>
      </PanelSectionRow>
      {exportStatus && <PanelSectionRow>{exportStatus}</PanelSectionRow>}
    </PanelSection>
  );

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
  const {
    currentGame,
    appId,
    protonPrefix,
    wineUserDirectory,
    graphics,
    runtime,
  } = diagnostics;

  if (currentGame == "Not detected")
    return (
      <>
        <PanelSection title="🎮 Game Diagnostic">
          <DiagnosticRow label="Current Game" value="No game running" />
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => void refresh()}>
              {isLoading ? "Refreshing…" : "Refresh diagnostics"}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      </>
    );
  return (
    <>
      <PanelSection title="🎮 Game Diagnostic">
        <DiagnosticRow label="Current Game" value={currentGame} />
        <DiagnosticRow label="Steam App ID" value={appId} />
        <DiagnosticRow label="Proton prefix" value={protonPrefix} />
        <DiagnosticRow
          label="Wine user directory"
          value={wineUserDirectory}
        />
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void refresh()}>
            {isLoading ? "Refreshing…" : "Refresh diagnostics"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Graphics">
        <DiagnosticRow label="API" value={graphics.api} />
        <DiagnosticRow label="Renderer" value={graphics.renderer} />
        <DiagnosticRow
          label="Detection Confidence"
          value={graphics.confidence}
        />
        <DiagnosticRow
          label="HDR Support"
          value={
            <StatusValue
              status={graphics.hdrSupport}
              label={
                graphics.hdrSupport === "enabled"
                  ? "Signals detected"
                  : undefined
              }
            />
          }
        />
        <DiagnosticRow
          label="HDR Configuration"
          value={
            <StatusValue
              status={graphics.hdrConfiguration}
              label={
                graphics.hdrConfiguration === "enabled" ? "Active" : undefined
              }
            />
          }
        />
        <DiagnosticRow
          label="Frame Generation"
          value={
            <StatusValue
              status={graphics.frameGenerationStatus}
              label={graphics.frameGeneration}
            />
          }
        />
        {graphics.frameGenerationStatus !== "unknown" && (
          <>
            <DiagnosticRow
              label="LSFG Attachment"
              value={graphics.frameGenerationAttachment}
            />
            <DiagnosticRow
              label="LSFG Target Process"
              value={graphics.frameGenerationProcess}
            />
            <DiagnosticRow
              label="LSFG Chain"
              value={graphics.frameGenerationChain}
            />
          </>
        )}
      </PanelSection>
      <PanelSection title="Runtime">
        <DiagnosticRow label="Process" value={runtime.process} />
        <DiagnosticRow label="Executable" value={runtime.executable} />
        <DiagnosticRow label="PID" value={runtime.pid} />
        <DiagnosticRow label="Parent" value={runtime.parent} />
        <DiagnosticRow label="Launch Command" value={runtime.launchCommand} />
        <DiagnosticRow label="Proton" value={runtime.proton} />
      </PanelSection>
      {exportActions}
    </>
  );
}

export default definePlugin(() => ({
  name: "Game Diagnostic",
  titleView: <div className={staticClasses.Title}>Game Diagnostic</div>,
  content: <Content />,
  icon: <FaStethoscope />,
}));
