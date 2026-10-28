import { useState } from "react";
import CallConsole from "./CallConsole.jsx";
import Dashboard from "./Dashboard.jsx";

export default function App() {
  const [page, setPage] = useState("call");

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-name">VaaniDesk</span>
          <span className="brand-sub">Voice support agent for Demo Bank</span>
        </div>
        <nav className="tabs" aria-label="Pages">
          <button aria-current={page === "call" ? "page" : undefined} onClick={() => setPage("call")}>
            Live call
          </button>
          <button aria-current={page === "dashboard" ? "page" : undefined} onClick={() => setPage("dashboard")}>
            Dashboard
          </button>
        </nav>
      </header>
      <main>{page === "call" ? <CallConsole /> : <Dashboard />}</main>
    </div>
  );
}
