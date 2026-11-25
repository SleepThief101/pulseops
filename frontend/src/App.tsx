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
  const { token, loading } = useAuth();
  const [activeTab, setActiveTab] = useState<NavTab>("dashboard");
  const [windowDays, setWindowDays] = useState<number>(30);
  const [eventsSourceFilter, setEventsSourceFilter] = useState<string>("");

  if (loading) {
    return (
      <div className="auth-main" style={{ minHeight: "100vh" }}>
        <div className="panel panel-pad" style={{ fontSize: "0.86rem", color: "var(--text-secondary)" }}>
          Loading PulseOps workspace...
        </div>
      </div>
    );
  }

  if (!token) {
    return <AuthPage />;
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
