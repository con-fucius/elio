import { useEffect, useState, type FormEvent } from "react";
import FieldWorkView from "./components/FieldWorkView";
import OperationsPane from "./components/OperationsPane";
import WorkBoard from "./components/WorkBoard";
import { getAccessToken } from "./lib/auth";
import { useConnectivity } from "./hooks/useConnectivity";
import { useLastSync } from "./hooks/useLastSync";
import { usePendingCommandCount } from "./hooks/usePendingCommandCount";
import { usePendingCommands } from "./hooks/usePendingCommands";
import { listWorkItems, type LocalWorkItem } from "./lib/localStore";
import { refreshFromServer } from "./lib/serverSync";
import { runFullSync } from "./lib/syncEngine";
import { fetchMe, login, logout, type MeResponse } from "./lib/sessionClient";

type AppTab = "work" | "ops";

interface HealthPayload {
  status: string;
  service: string;
  version: string;
}

function queueLabel(status: string): string {
  switch (status) {
    case "QUEUED":
      return "Not yet sent";
    case "IN_FLIGHT":
      return "Sending";
    case "ACCEPTED":
      return "Confirmed";
    case "REQUIRES_REVIEW":
      return "Waiting on review";
    case "CONFLICT":
      return "Conflict — action needed";
    case "REJECTED":
      return "Rejected";
    case "RETRYABLE_FAILURE":
      return "Will retry";
    default:
      return status;
  }
}

export default function App() {
  const { online } = useConnectivity();
  const { count: pendingCount, error: pendingError, refresh: refreshCount } =
    usePendingCommandCount();
  const { commands, refresh: refreshCommands } = usePendingCommands();
  const lastSync = useLastSync();
  const [healthError, setHealthError] = useState<string | null>(null);
  const [emailDraft, setEmailDraft] = useState("supervisor@alpha-hospital.test");
  const [passwordDraft, setPasswordDraft] = useState("SupervisorDev123!");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [session, setSession] = useState<MeResponse | null>(null);
  const [hasToken, setHasToken] = useState(Boolean(getAccessToken()));
  const [workItems, setWorkItems] = useState<LocalWorkItem[]>([]);
  const [tab, setTab] = useState<AppTab>("work");
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [showQueue, setShowQueue] = useState(false);

  const canAssign = session?.permissions?.includes("work_item.assign") ?? false;
  const canReview = session?.permissions?.includes("work_item.review") ?? false;
  const canCreate = session?.permissions?.includes("work_item.create") ?? false;
  const canExecute = session?.permissions?.includes("work_item.execute") ?? false;
  /** Field-first experience: worker with execute rights, not supervisor create/assign. */
  const isFieldWorker = canExecute && !canCreate && !canAssign;

  const refreshLocal = () => {
    refreshCount();
    refreshCommands();
    listWorkItems().then(setWorkItems).catch(() => setWorkItems([]));
  };

  const onRefreshServer = async () => {
    setRefreshBusy(true);
    setRefreshMsg(null);
    try {
      const result = await refreshFromServer(isFieldWorker ? "me" : "any");
      setRefreshMsg(
        isFieldWorker
          ? `Loaded ${result.work} job${result.work === 1 ? "" : "s"} assigned to you`
          : `Loaded ${result.work} work items · ${result.tasks} checklist steps`,
      );
      refreshLocal();
    } catch (err) {
      setRefreshMsg(err instanceof Error ? err.message : "Refresh failed — check connection");
    } finally {
      setRefreshBusy(false);
    }
  };

  useEffect(() => {
    refreshLocal();
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!getAccessToken()) {
        if (!cancelled) {
          setSession(null);
          setHealthError(null);
        }
        return;
      }
      try {
        const me = await fetchMe();
        if (!cancelled) setSession(me);
      } catch {
        if (!cancelled) setSession(null);
      }
      try {
        const res = await fetch("/api/v1/health/live");
        if (!res.ok) throw new Error("API unreachable");
        const body = (await res.json()) as HealthPayload;
        if (!cancelled) {
          setHealthError(null);
        }
        void body;
      } catch (err) {
        if (!cancelled) {
          setHealthError("API unreachable");
        }
      }
      if (!cancelled && getAccessToken()) {
        void onRefreshServer();
      }
    }
    void load();
  }, [online, hasToken]);

  const onLogin = async (e: FormEvent) => {
    e.preventDefault();
    setLoginError(null);
    try {
      await login(emailDraft.trim(), passwordDraft);
      setHasToken(true);
      refreshLocal();
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "Sign-in failed");
    }
  };

  const onLogout = async () => {
    await logout();
    setSession(null);
    setHasToken(false);
    setTab("work");
    refreshLocal();
  };

  const onSync = async () => {
    setSyncBusy(true);
    setSyncMsg(null);
    try {
      const summary = await runFullSync();
      setSyncMsg(
        summary.networkError
          ? "Could not reach the server. Nothing was lost — try again when online."
          : `Sent ${summary.accepted}. Conflicts ${summary.conflict}. Rejected ${summary.rejected}. Evidence ${summary.evidenceUploaded} uploaded.`,
      );
      refreshLocal();
      await onRefreshServer();
    } catch (err) {
      setSyncMsg(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setSyncBusy(false);
    }
  };

  const needsAttention = commands.filter(
    (c) => c.status === "CONFLICT" || c.status === "REJECTED" || c.status === "REQUIRES_REVIEW",
  );
  const waiting = commands.filter(
    (c) =>
      c.status === "QUEUED" ||
      c.status === "IN_FLIGHT" ||
      c.status === "RETRYABLE_FAILURE",
  );

  return (
    <div className="app">
      <header className="topbar" data-testid="global-chrome">
        <div className="topbar-left">
          <span className="brand">Elio</span>
          {hasToken && (
            <nav className="tabs" aria-label="Primary">
              <button
                type="button"
                className={tab === "work" ? "tab active" : "tab"}
                onClick={() => setTab("work")}
              >
                {isFieldWorker ? "My work" : "Field work"}
              </button>
              {(canAssign || canReview) && (
                <button
                  type="button"
                  className={tab === "ops" ? "tab active" : "tab"}
                  onClick={() => setTab("ops")}
                >
                  Operations
                </button>
              )}
            </nav>
          )}
        </div>
        <div className="topbar-right">
          {hasToken && (
            <>
              <span className="meta">{online ? "Online" : "Offline"}</span>
              <span className="meta">
                {pendingError
                  ? "Queue unavailable"
                  : pendingCount === 0
                    ? "Synced"
                    : `${pendingCount} unsent`}
              </span>
              <button type="button" className="btn-secondary" onClick={() => void onLogout()}>
                Sign out
              </button>
            </>
          )}
        </div>
      </header>

      <main className="shell">
        {!hasToken ? (
          <section className="panel narrow">
            <div className="panel-head">
              <h2>Sign in</h2>
            </div>
            <p className="muted">
              Pilot accounts: supervisor@alpha-hospital.test / SupervisorDev123! ·
              worker@alpha-hospital.test / WorkerDev123!
            </p>
            <form onSubmit={onLogin} className="login-form">
              <label>
                Email
                <input
                  type="email"
                  value={emailDraft}
                  onChange={(e) => setEmailDraft(e.target.value)}
                  autoComplete="username"
                  required
                />
              </label>
              <label>
                Password
                <input
                  type="password"
                  value={passwordDraft}
                  onChange={(e) => setPasswordDraft(e.target.value)}
                  autoComplete="current-password"
                  required
                />
              </label>
              <button type="submit" className="btn-primary">
                Sign in
              </button>
              {loginError && (
                <p className="error" data-testid="login-error">
                  {loginError}
                </p>
              )}
            </form>
          </section>
        ) : (
          <>
            <div className="toolbar">
              <div>
                <h1 className="page-title">
                  {tab === "work"
                    ? isFieldWorker
                      ? "My work"
                      : "Field work"
                    : "Operations"}
                </h1>
                <p className="lede">
                  {session ? `${session.display_name} · ${session.tenant_slug}` : ""}
                  {lastSync ? ` · Last confirmed sync ${new Date(lastSync).toLocaleString()}` : ""}
                </p>
              </div>
              <div className="toolbar-actions">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => void onRefreshServer()}
                  disabled={refreshBusy || !online}
                >
                  {refreshBusy ? "Refreshing…" : "Refresh"}
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => void onSync()}
                  disabled={syncBusy || !online}
                >
                  {syncBusy ? "Sending…" : "Send pending"}
                </button>
              </div>
            </div>

            {refreshMsg && <p className="muted status-line" data-testid="refresh-msg">{refreshMsg}</p>}
            {syncMsg && <p className="muted status-line" data-testid="sync-msg">{syncMsg}</p>}
            {!online && (
              <p className="warn status-line">
                Offline. Work stays on this device until you send pending.
              </p>
            )}

            <section className="panel strip" data-testid="sync-center">
              <div className="strip-row">
                <span>
                  {needsAttention.length > 0
                    ? `${needsAttention.length} need attention`
                    : waiting.length > 0
                      ? `${waiting.length} waiting to send`
                      : "Device queue clear"}
                </span>
                <button
                  type="button"
                  className="linkish"
                  onClick={() => setShowQueue((v) => !v)}
                >
                  {showQueue ? "Hide detail" : "Show detail"}
                </button>
              </div>
              {showQueue && (
                <div className="queue-detail">
                  {needsAttention.map((c) => (
                    <div key={c.commandId} className="queue-row attention">
                      <span>{c.commandType}</span>
                      <span>{queueLabel(c.status)}</span>
                      {c.reasonCode && <code>{c.reasonCode}</code>}
                      {c.lastError && <span className="error">{c.lastError}</span>}
                    </div>
                  ))}
                  {waiting.map((c) => (
                    <div key={c.commandId} className="queue-row">
                      <span>{c.commandType}</span>
                      <span>{queueLabel(c.status)}</span>
                    </div>
                  ))}
                  {needsAttention.length === 0 && waiting.length === 0 && (
                    <p className="muted">No pending device commands.</p>
                  )}
                </div>
              )}
            </section>

            {tab === "work" ? (
              isFieldWorker ? (
                <FieldWorkView
                  workItems={workItems}
                  online={online}
                  onChanged={refreshLocal}
                />
              ) : (
                <WorkBoard
                  workItems={workItems}
                  online={online}
                  onChanged={refreshLocal}
                />
              )
            ) : (
              <OperationsPane
                online={online}
                onChanged={refreshLocal}
                canAssign={canAssign}
                canReview={canReview}
              />
            )}

            {!online && healthError && (
              <p className="muted">API offline: {healthError}</p>
            )}
          </>
        )}
      </main>
    </div>
  );
}
