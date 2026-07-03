import TeammateWorkspace from "./TeammateWorkspace";

const OUTBOUND_PATH = "/outbound";

function LegacyWorkspaceShell() {
  return (
    <iframe
      src="/reference-ui/index.html"
      title="视频号团购商家AI获客客户端"
      style={{
        width: "100vw",
        height: "100vh",
        border: 0,
        display: "block",
        background: "#eaf5ff",
      }}
    />
  );
}

function App() {
  const pathname = window.location.pathname.replace(/\/+$/, "") || "/";
  if (pathname === OUTBOUND_PATH) {
    return <TeammateWorkspace />;
  }
  return <LegacyWorkspaceShell />;
}

export default App;
