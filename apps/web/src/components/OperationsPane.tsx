import { useCallback, useEffect, useState } from "react";
import { listActors, type ActorRead } from "../lib/actorsClient";
import {
  exceptionCategoryText,
  listWorkExceptions,
  type WorkExceptionRow,
} from "../lib/exceptionsClient";
import { useConnectivity } from "../hooks/useConnectivity";
import {
  loadOpsWork,
  rowActions,
  statusText,
  submitAcceptReview,
  submitAssign,
  submitBeginReview,
  submitCancel,
  submitRejectReview,
  submitUnblock,
} from "../lib/opsClient";
import type { ServerWorkItem } from "../lib/serverSync";
import { usePendingCommandCount } from "../hooks/usePendingCommandCount";
import { runFullSync } from "../lib/syncEngine";

type Props = {
  online: boolean;
  onChanged: () => void;
  canReview: boolean;
  canAssign: boolean;
};

export default function OperationsPane({
  online,
  onChanged,
  canReview,
  canAssign,
}: Props) {
  const { online: liveOnline } = useConnectivity();
  const { count: pendingCount, refresh: refreshCount } = usePendingCommandCount();
  const [rows, setRows] = useState<ServerWorkItem[]>([]);
  const [actors, setActors] = useState<ActorRead[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [openExceptions, setOpenExceptions] = useState<WorkExceptionRow[]>([]);
  const [assignee, setAssignee] = useState("");
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<"actionable" | "all" | "review">("actionable");
  void online;

  const load = useCallback(async () => {
    try {
      const all = await loadOpsWork("all");
      setRows(all);
    } catch (err) {
      // Offline: keep last loaded server snapshot; decisions still queue.
      setMsg(
        liveOnline
          ? err instanceof Error
            ? err.message
            : "Could not load work"
          : "Offline — showing last loaded list. Decisions are saved on this device.",
      );
    }
  }, [liveOnline]);

  useEffect(() => {
    void load();
    listActors().then(setActors).catch(() => setActors([]));
  }, [load]);

  const filtered = rows.filter((r) => {
    if (filter === "all") return true;
    if (filter === "review") {
      return r.status === "SUBMITTED" || r.status === "UNDER_REVIEW";
    }
    return ["READY", "ASSIGNED", "BLOCKED", "SUBMITTED", "UNDER_REVIEW", "IN_PROGRESS"].includes(
      r.status,
    );
  });

  const selected = rows.find((r) => r.id === selectedId) ?? null;

  useEffect(() => {
    if (!selected || selected.status !== "BLOCKED") {
      setOpenExceptions([]);
      return;
    }
    listWorkExceptions(selected.id, true)
      .then(setOpenExceptions)
      .catch(() => setOpenExceptions([]));
  }, [selectedId, selected?.status, rows]);

  const act = async (fn: () => Promise<void>, label: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      refreshCount();
      if (liveOnline) {
        await load();
        setMsg(`${label} saved and sent.`);
      } else {
        setMsg(`${label} saved on this device. It will send when you are online.`);
      }
      onChanged();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : `${label} failed`);
    } finally {
      setBusy(false);
    }
  };

  const onSendQueue = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const summary = await runFullSync();
      refreshCount();
      await load();
      onChanged();
      setMsg(
        summary.networkError
          ? "Could not send. Commands remain queued."
          : `Sent ${summary.accepted} command(s). Conflicts ${summary.conflict}. Rejected ${summary.rejected}.`,
      );
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Send failed");
    } finally {
      setBusy(false);
    }
  };

  const onRowAction = async (row: ServerWorkItem, actionId: string) => {
    if (actionId === "assign") {
      if (!assignee) {
        setMsg("Select someone to assign");
        return;
      }
      await act(() => submitAssign(row.id, assignee, reason), "Assignment");
      setAssignee("");
      setReason("");
      return;
    }
    if (actionId === "begin_review") {
      await act(() => submitBeginReview(row.id), "Review started");
      return;
    }
    if (actionId === "unblock") {
      await act(() => submitUnblock(row.id, reason || "Cleared"), "Work unblocked");
      return;
    }
    if (actionId === "accept_review") {
      await act(() => submitAcceptReview(row.id, reason), "Review accepted");
      setReason("");
      return;
    }
    if (actionId === "reject_review") {
      if (!reason.trim()) {
        setMsg("Rejection needs a reason");
        return;
      }
      await act(() => submitRejectReview(row.id, reason), "Review rejected");
      setReason("");
      return;
    }
    if (actionId === "cancel") {
      if (!reason.trim()) {
        setMsg("Cancel needs a reason");
        return;
      }
      await act(() => submitCancel(row.id, reason), "Cancelled");
      setReason("");
    }
  };

  return (
    <section className="panel" data-testid="ops-pane">
      <div className="panel-head">
        <h2>Operations</h2>
        <div className="toolbar-actions">
          {!liveOnline && (
            <span className="meta">
              {pendingCount > 0 ? `${pendingCount} unsent` : "Offline"}
            </span>
          )}
          <button
            type="button"
            className="btn-secondary"
            onClick={() => void load()}
            disabled={busy}
          >
            Refresh
          </button>
          {pendingCount > 0 && (
            <button
              type="button"
              className="btn-primary"
              onClick={() => void onSendQueue()}
              disabled={busy || !liveOnline}
            >
              Send pending
            </button>
          )}
        </div>
      </div>

      <div className="ops-filters">
        <button
          type="button"
          className={filter === "actionable" ? "filter active" : "filter"}
          onClick={() => setFilter("actionable")}
        >
          Needs action
        </button>
        <button
          type="button"
          className={filter === "review" ? "filter active" : "filter"}
          onClick={() => setFilter("review")}
        >
          Review
        </button>
        <button
          type="button"
          className={filter === "all" ? "filter active" : "filter"}
          onClick={() => setFilter("all")}
        >
          All
        </button>
      </div>

      <div className="ops-layout">
        <div className="ops-list">
          {filtered.length === 0 && <p className="muted">Nothing in this view.</p>}
          <table className="ops-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Type</th>
                <th>Status</th>
                <th>Exceptions</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr
                  key={r.id}
                  className={selectedId === r.id ? "selected" : ""}
                  onClick={() => setSelectedId(r.id)}
                >
                  <td>{r.title}</td>
                  <td className="muted">{r.work_type}</td>
                  <td>{statusText(r.status)}</td>
                  <td className="muted">
                    {r.exception_count > 0 ? String(r.exception_count) : "—"}
                  </td>
                  <td>
                    {(canAssign || canReview) &&
                      rowActions(r.status).map((a) => (
                        <button
                          key={a.id}
                          type="button"
                          className={a.primary ? "btn-primary btn-sm" : "btn-secondary btn-sm"}
                          disabled={busy || !liveOnline}
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedId(r.id);
                            void onRowAction(r, a.id);
                          }}
                        >
                          {a.label}
                        </button>
                      ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {selected && (
          <aside className="ops-detail">
            <h3>{selected.title}</h3>
            <p className="muted">
              {statusText(selected.status)} · {selected.work_type}
              {selected.exception_count > 0
                ? ` · ${selected.exception_count} exception${selected.exception_count === 1 ? "" : "s"}`
                : ""}
            </p>

            {selected.status === "BLOCKED" && openExceptions.length > 0 && (
              <div className="exception-list" data-testid="ops-exceptions">
                <h4>Reported blocks</h4>
                {openExceptions.map((ex) => (
                  <div key={ex.id} className="exception-item">
                    <strong>{exceptionCategoryText(ex.category)}</strong>
                    <p className="muted">{ex.detail || "No further detail"}</p>
                    <p className="muted">
                      Raised {new Date(ex.raised_at).toLocaleString()}
                    </p>
                  </div>
                ))}
              </div>
            )}

            {selected.status === "READY" && canAssign && (
              <label className="block">
                Assign to
                <select value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                  <option value="">Select…</option>
                  {actors.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.display_name}
                    </option>
                  ))}
                </select>
              </label>
            )}

            {(selected.status === "SUBMITTED" || selected.status === "UNDER_REVIEW") &&
              canReview && (
                <label className="block">
                  Review note
                  <input
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Required for reject; optional for accept"
                  />
                </label>
              )}

            {["ASSIGNED", "SUBMITTED", "IN_PROGRESS", "BLOCKED"].includes(selected.status) && (
              <label className="block">
                Reason (cancel / unblock)
                <input
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Required to cancel"
                />
              </label>
            )}

            {msg && (
              <p className="muted" data-testid="ops-msg">
                {msg}
              </p>
            )}
          </aside>
        )}
      </div>
    </section>
  );
}