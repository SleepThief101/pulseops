import { useState } from "react";
import { Layout, type NavTab } from "./components/Layout";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { AuthPage } from "./pages/AuthPage";
import { CopilotPage } from "./pages/CopilotPage";
import { DashboardPage } from "./pages/DashboardPage";
import { EventsPage } from "./pages/EventsPage";
import { IntegrationsPage } from "./pages/IntegrationsPage";
import { TeamPage } from "./pages/TeamPage";

function ControlTowerShell() {
  const { token, loading, sessionError, retrySession, logout } = useAuth();
  const [activeTab, setActiveTab] = useState<NavTab>("dashboard");
  const [windowDays, setWindowDays] = useState<number>(30);
  const [eventsSourceFilter, setEventsSourceFilter] = useState<string>("");

  if (loading) {
    return (
      <div className="auth-main" style={{ minHeight: "100vh" }}>
        <div className="panel panel-pad" style={{ maxWidth: 420, textAlign: "center" }}>
          <div style={{ fontSize: "1rem", fontWeight: 500, color: "var(--text-primary)" }}>
            Loading PulseOps workspace…
          </div>
          <div style={{ fontSize: "0.875rem", color: "var(--text-muted)", marginTop: 8 }}>
            If the API service is waking from idle sleep, initial connection may take up to 45 seconds.
          </div>
        </div>
      </div>
    );
  }

  if (!token) {
    return <AuthPage />;
  }

  if (sessionError) {
    return (
      <div className="auth-main" style={{ minHeight: "100vh" }}>
        <div className="auth-card" style={{ maxWidth: 440 }}>
          <h1 className="panel-title" style={{ marginBottom: 8 }}>
            Control Tower Reconnecting
          </h1>
          <p className="panel-subtitle" style={{ marginBottom: 18 }}>
            {sessionError}
          </p>
          <div className="row-actions">
            <button type="button" className="btn" onClick={() => retrySession()}>
              Retry Connection
            </button>
            <button type="button" className="btn btn-secondary" onClick={logout}>
              Sign Out
            </button>
          </div>
        </div>
      </div>
    );
  }

  function handleSelectTab(tab: NavTab) {
    if (tab !== "events") {
      setEventsSourceFilter("");
    }
    setActiveTab(tab);
  }

  return (
    <Layout
      activeTab={activeTab}
      onSelectTab={handleSelectTab}
      windowDays={windowDays}
      onChangeWindowDays={setWindowDays}
    >
      {activeTab === "dashboard" && (
        <DashboardPage
          windowDays={windowDays}
          onGoToIntegrations={() => setActiveTab("integrations")}
          onDrilldownEvents={(source) => {
            setEventsSourceFilter(source);
            setActiveTab("events");
          }}
        />
      )}
      {activeTab === "integrations" && <IntegrationsPage />}
      {activeTab === "events" && <EventsPage initialSource={eventsSourceFilter} />}
      {activeTab === "copilot" && <CopilotPage />}
      {activeTab === "team" && <TeamPage />}
    </Layout>
  );
}

export function App() {
  return (
    <AuthProvider>
      <ControlTowerShell />
    </AuthProvider>
  );
}

export default App;
