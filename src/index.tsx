import { PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { FaStethoscope } from "react-icons/fa";

function Content() {
  return (
    <PanelSection title="Game Diagnostic">
      <PanelSectionRow>
        <div>
          <div className={staticClasses.Label}>Hello, Steam Deck!</div>
          <div style={{ opacity: 0.7 }}>Game Diagnostic is ready.</div>
        </div>
      </PanelSectionRow>
    </PanelSection>
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
