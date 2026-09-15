import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import {
  enqueuePendingEvidence,
  listPendingEvidence,
  listWorkTasks,
  type LocalWorkItem,
  type LocalWorkTask,
  type PendingEvidence,
} from "../lib/localStore";
import {
  downloadEvidence,
  listEvidence,
  type EvidenceListItem,
} from "../lib/evidenceClient";
import { listTemplates, type TemplateRead } from "../lib/templatesClient";
import {
  exceptionCategoryText,
  listWorkExceptions,
  type WorkExceptionRow,
} from "../lib/exceptionsClient";
import { statusText } from "../lib/opsClient";
import { WorkCommands } from "../lib/workActions";

type Props = {
  workItems: LocalWorkItem[];
  online: boolean;
  onChanged: () => void;
};

const EXCEPTION_CATEGORIES = [
  { id: "no_access", label: "Cannot get in / site closed" },
  { id: "unsafe", label: "Unsafe to work here" },
  { id: "wrong_site", label: "Wrong site or wrong job" },
  { id: "missing_asset", label: "Equipment or stock missing" },
  { id: "other", label: "Something else" },
] as const;

function nextActionLabel(status: string, pendingRequired: number): string | null {
  switch (status) {
    case "ASSIGNED":
      return "Accept this job";
    case "ACCEPTED":
      return "Start work";
    case "IN_PROGRESS":
      return pendingRequired > 0
        ? `Finish ${pendingRequired} checklist item${pendingRequired === 1 ? "" : "s"}`
        : "Submit when ready";
    case "BLOCKED":
      return "Waiting on supervisor";
    case "SUBMITTED":
      return "Sent for review";
    case "REJECTED":
      return "Fix and resubmit";
    case "UNDER_REVIEW":
      return "In supervisor review";
    default:
      return null;
  }
}

export default function FieldWorkView({ workItems, online, onChanged }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tasks, setTasks] = useState<LocalWorkTask[]>([]);
  const [pendingEvidence, setPendingEvidence] = useState<PendingEvidence[]>([]);
  const [serverEvidence, setServerEvidence] = useState<EvidenceListItem[]>([]);
  const [openExceptions, setOpenExceptions] = useState<WorkExceptionRow[]>([]);
  const [templates, setTemplates] = useState<TemplateRead[]>([]);
  const [taskDrafts, setTaskDrafts] = useState<
    Record<string, { notes: string; fieldValues: Record<string, string> }>
  >({});
  const [activeStepId, setActiveStepId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [outcomeType, setOutcomeType] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [evidenceType, setEvidenceType] = useState("photo");
  const [evidenceFile, setEvidenceFile] = useState<File | null>(null);
  const [exceptionCategory, setExceptionCategory] = useState("");
  const [exceptionDetail, setExceptionDetail] = useState("");
  const [showException, setShowException] = useState(false);

  const selected = workItems.find((w) => w.id === selectedId) ?? null;
  const selectedTemplate = useMemo(
    () => templates.find((t) => t.work_type === selected?.workType) ?? null,
    [templates, selected?.workType],
  );

  useEffect(() => {
    listTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, []);

  const refreshTasks = useCallback(async (workId: string | null) => {
    if (!workId) {
      setTasks([]);
      setActiveStepId(null);
      return;
    }
    const rows = await listWorkTasks(workId);
    setTasks(rows);
    const firstPending = rows.find((t) => t.status === "PENDING");
    setActiveStepId(firstPending?.id ?? rows[0]?.id ?? null);
  }, []);

  const refreshEvidence = useCallback(() => {
    listPendingEvidence()
      .then((rows) =>
        setPendingEvidence(selectedId ? rows.filter((r) => r.workItemId === selectedId) : []),
      )
      .catch(() => setPendingEvidence([]));
    if (selectedId) {
      listEvidence(selectedId).then(setServerEvidence).catch(() => setServerEvidence([]));
    } else {
      setServerEvidence([]);
    }
  }, [selectedId]);

  useEffect(() => {
    void refreshTasks(selectedId);
    refreshEvidence();
    setOutcomeType("");
    setReason("");
    setShowException(false);
    setExceptionCategory("");
    setExceptionDetail("");
    setTaskDrafts({});
    if (selectedId && (selected?.status === "BLOCKED" || workItems.find((w) => w.id === selectedId)?.status === "BLOCKED")) {
      listWorkExceptions(selectedId, true)
        .then(setOpenExceptions)
        .catch(() => setOpenExceptions([]));
    } else {
      setOpenExceptions([]);
    }
  }, [
    selectedId,
    selected?.status,
    refreshTasks,
    refreshEvidence,
    workItems,
  ]);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg(
        online
          ? `${label} saved.`
          : `${label} saved on this device. Tap Send to upload.`,
      );
      onChanged();
      await refreshTasks(selectedId);
      refreshEvidence();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : `${label} failed`);
    } finally {
      setBusy(false);
    }
  };

  const requiredTasks = tasks.filter((t) => t.required);
  const pendingRequired = requiredTasks.filter((t) => t.status === "PENDING");
  const checklistComplete = tasks.length === 0 || pendingRequired.length === 0;
  const canSubmitException = EXCEPTION_CATEGORIES.some((c) => c.id === exceptionCategory);

  const activeTask =
    tasks.find((t) => t.id === activeStepId) ?? tasks.find((t) => t.status === "PENDING") ?? null;

  const draft = activeTask
    ? (taskDrafts[activeTask.id] ?? {
        notes: activeTask.notes,
        fieldValues: activeTask.fieldValues,
      })
    : { notes: "", fieldValues: {} };

  const setDraftField = (taskId: string, key: string, value: string) => {
    setTaskDrafts((prev) => {
      const cur = prev[taskId] ?? { notes: "", fieldValues: {} };
      return {
        ...prev,
        [taskId]: {
          notes: cur.notes,
          fieldValues: { ...cur.fieldValues, [key]: value },
        },
      };
    });
  };

  const setDraftNotes = (taskId: string, notes: string) => {
    setTaskDrafts((prev) => {
      const cur = prev[taskId] ?? { notes: "", fieldValues: {} };
      return {
        ...prev,
        [taskId]: { notes, fieldValues: cur.fieldValues },
      };
    });
  };

  const onAccept = () => run("Accept", () => WorkCommands.accept(selected!.id));
  const onStart = () => run("Start", () => WorkCommands.start(selected!.id));
  const onSubmit = async () => {
    if (!selected) return;
    if (tasks.length > 0 && !checklistComplete && !canSubmitException) {
      setMsg(
        `Finish ${pendingRequired.length} required checklist item(s) before submitting, or report that you cannot continue.`,
      );
      return;
    }
    const outcome =
      outcomeType || selectedTemplate?.default_outcome_type || "COMPLETED";
    await run("Submit", () => WorkCommands.submit(selected.id, reason, outcome));
  };

  const onCompleteStep = async (task: LocalWorkTask) => {
    if (!selected) return;
    await run(`Done: ${task.title}`, () =>
      WorkCommands.completeTask(
        selected.id,
        task.id,
        draft.notes,
        draft.fieldValues,
      ),
    );
    const next = tasks.find((t) => t.id !== task.id && t.status === "PENDING");
    setActiveStepId(next?.id ?? null);
  };

  const onSaveStep = async (task: LocalWorkTask) => {
    if (!selected) return;
    await run("Saved", () =>
      WorkCommands.saveTaskDraft(selected.id, task.id, draft.notes, draft.fieldValues),
    );
  };

  const onSkipStep = async (task: LocalWorkTask) => {
    if (!selected) return;
    await run("Skipped", () => WorkCommands.skipTask(selected.id, task.id, draft.notes));
  };

  const onException = async () => {
    if (!selected || !exceptionCategory) {
      setMsg("Choose what went wrong");
      return;
    }
    if (!exceptionDetail.trim()) {
      setMsg("Add a short note");
      return;
    }
    await run("Reported blocked", () =>
      WorkCommands.raiseException(
        selected.id,
        `${exceptionCategory}| ${exceptionDetail.trim()}`,
      ),
    );
    setShowException(false);
    setExceptionCategory("");
    setExceptionDetail("");
  };

  const onEvidence = async (e: FormEvent) => {
    e.preventDefault();
    if (!selected || !evidenceFile) {
      setMsg("Choose a photo or file");
      return;
    }
    await enqueuePendingEvidence({
      workItemId: selected.id,
      workTaskId: activeTask?.id || undefined,
      evidenceType,
      file: evidenceFile,
      fileName: evidenceFile.name,
    });
    setEvidenceFile(null);
    setMsg(online ? "Photo saved. Send to upload." : "Photo saved on device until you send.");
    onChanged();
    refreshEvidence();
  };

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    setEvidenceFile(e.target.files?.[0] ?? null);
  };

  const download = async (ev: EvidenceListItem) => {
    try {
      const { blob, name } = await downloadEvidence(ev.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Download failed");
    }
  };

  const actionable = workItems.filter((w) =>
    ["ASSIGNED", "ACCEPTED", "IN_PROGRESS", "BLOCKED", "SUBMITTED", "REJECTED", "UNDER_REVIEW"].includes(
      w.status,
    ),
  );
  const completed = workItems.filter((w) =>
    ["COMPLETED", "CANCELLED", "EXPIRED"].includes(w.status),
  );
  const list = actionable.length > 0 ? actionable : workItems.filter((w) => !["COMPLETED", "CANCELLED", "EXPIRED"].includes(w.status));

  return (
    <section className="panel" data-testid="field-work">
      <div className="panel-head">
        <h2>My work</h2>
      </div>

      <div className="work-layout">
        <aside className="work-list-pane">
          <h3 className="section-label">Assigned to you</h3>
          {list.length === 0 ? (
            <p className="muted">
              No open jobs. If you expect work today, ask your supervisor to assign it, then
              Refresh.
            </p>
          ) : (
            <ul className="work-list">
              {list.map((w) => (
                <li key={w.id}>
                  <button
                    type="button"
                    className={selectedId === w.id ? "work-link active" : "work-link"}
                    onClick={() => setSelectedId(w.id)}
                  >
                    <span className="work-link-title">{w.title}</span>
                    <span className="work-link-meta">
                      <span className="status-text">{statusText(w.status)}</span>
                      <span className="status-text muted">{w.workType}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {completed.length > 0 && (
            <div className="done-today" data-testid="done-today">
              <h3 className="section-label">Done</h3>
              <ul className="work-list">
                {completed.map((w) => (
                  <li key={w.id}>
                    <button
                      type="button"
                      className={selectedId === w.id ? "work-link active done" : "work-link done"}
                      onClick={() => setSelectedId(w.id)}
                    >
                      <span className="work-link-title">{w.title}</span>
                      <span className="status-text">{statusText(w.status)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>

        <div className="work-detail-pane">
          {!selected ? (
            <p className="muted">Select a job from the list to see what to do next.</p>
          ) : (
            <div className="guided" data-testid="guided-work">
              <div className="guided-head">
                <h3>{selected.title}</h3>
                <p className="muted">
                  {selectedTemplate?.title ?? selected.workType} · {statusText(selected.status)}
                </p>
                {nextActionLabel(selected.status, pendingRequired.length) && (
                  <p className="next-action" data-testid="next-action">
                    {nextActionLabel(selected.status, pendingRequired.length)}
                  </p>
                )}
              </div>

              {selected.status === "BLOCKED" && openExceptions.length > 0 && (
                <div className="exception-box" data-testid="worker-exceptions">
                  <h4>Why this is blocked</h4>
                  {openExceptions.map((ex) => (
                    <div key={ex.id} className="exception-item">
                      <strong>{exceptionCategoryText(ex.category)}</strong>
                      <p className="muted">{ex.detail || "No further detail"}</p>
                    </div>
                  ))}
                  <p className="muted">Your supervisor can unblock this once cleared.</p>
                </div>
              )}

              {/* Primary actions */}
              <div className="guided-actions">
                {selected.status === "ASSIGNED" && (
                  <button
                    type="button"
                    className="btn-primary btn-lg"
                    disabled={busy}
                    onClick={() => void onAccept()}
                    data-testid="accept-job"
                  >
                    Accept job
                  </button>
                )}
                {selected.status === "ACCEPTED" && (
                  <button
                    type="button"
                    className="btn-primary btn-lg"
                    disabled={busy}
                    onClick={() => void onStart()}
                    data-testid="start-job"
                  >
                    Start work
                  </button>
                )}
                {(selected.status === "IN_PROGRESS" ||
                  selected.status === "BLOCKED" ||
                  selected.status === "REJECTED") &&
                  (checklistComplete || canSubmitException || selected.status === "BLOCKED") && (
                    <button
                      type="button"
                      className="btn-primary btn-lg"
                      disabled={busy}
                      onClick={() => void onSubmit()}
                      data-testid="submit-job"
                    >
                      Submit
                    </button>
                  )}
                {(selected.status === "IN_PROGRESS" || selected.status === "ACCEPTED") && (
                  <button
                    type="button"
                    className="btn-secondary"
                    disabled={busy}
                    onClick={() => setShowException((v) => !v)}
                    data-testid="toggle-exception"
                  >
                    I cannot continue
                  </button>
                )}
              </div>

              {showException && (
                <div className="exception-box" data-testid="exception-box">
                  <h4>What is stopping you?</h4>
                  <label className="block">
                    Situation
                    <select
                      value={exceptionCategory}
                      onChange={(e) => setExceptionCategory(e.target.value)}
                    >
                      <option value="">Select…</option>
                      {EXCEPTION_CATEGORIES.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {exceptionCategory && (
                    <label className="block">
                      Short note for your supervisor
                      <input
                        value={exceptionDetail}
                        onChange={(e) => setExceptionDetail(e.target.value)}
                        placeholder="e.g. Gate locked, no guard on site"
                      />
                    </label>
                  )}
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={busy}
                    onClick={() => void onException()}
                  >
                    Report blocked
                  </button>
                </div>
              )}

              {(selected.status === "IN_PROGRESS" ||
                selected.status === "BLOCKED" ||
                selected.status === "ACCEPTED") &&
                tasks.length > 0 && (
                  <div className="guided-steps" data-testid="guided-steps">
                    <div className="steps-head">
                      <h4>Checklist</h4>
                      <span className="muted">
                        {requiredTasks.length - pendingRequired.length} of{" "}
                        {requiredTasks.length} required done
                      </span>
                    </div>

                    <ol className="step-list">
                      {tasks.map((t, i) => {
                        const isActive = t.id === activeTask?.id;
                        const d = taskDrafts[t.id] ?? {
                          notes: t.notes,
                          fieldValues: t.fieldValues,
                        };
                        return (
                          <li
                            key={t.id}
                            className={`step-item ${
                              isActive ? "active" : ""
                            } status-${t.status}`}
                          >
                            <button
                              type="button"
                              className="step-header"
                              onClick={() => setActiveStepId(t.id)}
                            >
                              <span className="step-num">{i + 1}</span>
                              <span className="step-title">{t.title}</span>
                              <span className="status-text">
                                {t.status === "PENDING"
                                  ? "To do"
                                  : t.status === "COMPLETED"
                                    ? "Done"
                                    : "Skipped"}
                              </span>
                            </button>

                            {isActive && t.status === "PENDING" && (
                              <div className="step-body">
                                {t.description && <p className="muted">{t.description}</p>}
                                {t.fields.map((f) => (
                                  <label key={f.key} className="block">
                                    {f.label}
                                    {f.type === "choice" && f.options?.length ? (
                                      <select
                                        value={d.fieldValues[f.key] ?? ""}
                                        onChange={(e) =>
                                          setDraftField(t.id, f.key, e.target.value)
                                        }
                                      >
                                        <option value="">Select…</option>
                                        {f.options.map((o) => (
                                          <option key={o} value={o}>
                                            {o}
                                          </option>
                                        ))}
                                      </select>
                                    ) : (
                                      <input
                                        value={d.fieldValues[f.key] ?? ""}
                                        onChange={(e) =>
                                          setDraftField(t.id, f.key, e.target.value)
                                        }
                                      />
                                    )}
                                  </label>
                                ))}
                                <label className="block">
                                  Notes
                                  <input
                                    value={d.notes}
                                    onChange={(e) => setDraftNotes(t.id, e.target.value)}
                                    placeholder="Optional"
                                  />
                                </label>
                                {t.requiredEvidenceTypes.length > 0 && (
                                  <p className="muted">
                                    This step needs: {t.requiredEvidenceTypes.join(", ")}
                                  </p>
                                )}
                                <div className="guided-actions">
                                  <button
                                    type="button"
                                    className="btn-primary"
                                    disabled={busy}
                                    onClick={() => void onCompleteStep(t)}
                                  >
                                    Mark done
                                  </button>
                                  <button
                                    type="button"
                                    className="btn-secondary"
                                    disabled={busy}
                                    onClick={() => void onSaveStep(t)}
                                  >
                                    Save
                                  </button>
                                  {!t.required && (
                                    <button
                                      type="button"
                                      className="btn-secondary"
                                      disabled={busy}
                                      onClick={() => void onSkipStep(t)}
                                    >
                                      Skip
                                    </button>
                                  )}
                                </div>
                              </div>
                            )}
                            {isActive && t.status !== "PENDING" && t.notes && (
                              <p className="muted step-body">{t.notes}</p>
                            )}
                          </li>
                        );
                      })}
                    </ol>
                  </div>
                )}

              {/* Evidence — prominent during execution */}
              {["IN_PROGRESS", "ACCEPTED", "BLOCKED"].includes(selected.status) && (
                <form
                  onSubmit={(e) => void onEvidence(e)}
                  className="evidence-form"
                  data-testid="evidence-form"
                >
                  <h4>Photos and files</h4>
                  <label className="block">
                    Add to step
                    <select
                      value={activeTask?.id ?? ""}
                      onChange={(e) => setActiveStepId(e.target.value || null)}
                    >
                      <option value="">This job</option>
                      {tasks.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.sequence}. {t.title}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    Type
                    <select
                      value={evidenceType}
                      onChange={(e) => setEvidenceType(e.target.value)}
                    >
                      <option value="photo">Photo</option>
                      <option value="document">Document</option>
                      <option value="observation">Observation</option>
                    </select>
                  </label>
                  <input
                    type="file"
                    accept="image/*,application/pdf"
                    capture="environment"
                    onChange={onFile}
                  />
                  <button
                    type="submit"
                    className="btn-primary"
                    disabled={busy || !evidenceFile}
                  >
                    Add photo / file
                  </button>
                  {pendingEvidence.length > 0 && (
                    <ul className="task-list">
                      {pendingEvidence.map((p) => (
                        <li key={p.localId} className="task-row">
                          {p.evidenceType} · {p.fileName ?? "file"} · on device
                        </li>
                      ))}
                    </ul>
                  )}
                  {serverEvidence.length > 0 && (
                    <ul className="task-list" data-testid="server-evidence">
                      {serverEvidence.map((ev) => (
                        <li key={ev.id} className="task-row evidence-row">
                          <span>
                            {ev.evidence_type} ·{" "}
                            {ev.size_bytes != null && ev.size_bytes < 1024
                              ? `${ev.size_bytes} B`
                              : ev.size_bytes != null
                                ? `${Math.round(ev.size_bytes / 1024)} KB`
                                : ""}
                          </span>
                          {(ev.verification_status === "UPLOADED" ||
                            ev.verification_status === "VERIFIED") && (
                            <button
                              type="button"
                              className="btn-secondary"
                              onClick={() => void download(ev)}
                            >
                              Download
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </form>
              )}

              {(selected.status === "IN_PROGRESS" || selected.status === "REJECTED") && (
                <>
                  <label className="block">
                    Outcome
                    <select
                      value={outcomeType}
                      onChange={(e) => setOutcomeType(e.target.value)}
                    >
                      <option value="">
                        {selectedTemplate?.default_outcome_type ?? "COMPLETED"} (default)
                      </option>
                      {(selectedTemplate?.outcome_types ?? [
                        "COMPLETED",
                        "PARTIALLY_COMPLETED",
                        "UNABLE_TO_ACCESS",
                        "FAILED",
                      ]).map((o) => (
                        <option key={o} value={o}>
                          {o}
                        </option>
                      ))}
                    </select>
                  </label>
                  {!checklistComplete && !canSubmitException && (
                    <p className="warn">
                      Complete required steps before submit — or use “I cannot continue”.
                    </p>
                  )}
                </>
              )}

              {selected.status === "SUBMITTED" && (
                <p className="muted">Submitted. Your supervisor is reviewing this job.</p>
              )}
              {selected.status === "UNDER_REVIEW" && (
                <p className="muted">This job is in review.</p>
              )}
              {selected.status === "COMPLETED" && (
                <p className="muted">Completed. Thank you.</p>
              )}

              {!online && (
                <p className="warn">
                  Offline. Work stays on this device until you tap Send.
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {msg && (
        <p className="muted status-line" data-testid="field-msg">
          {msg}
        </p>
      )}
    </section>
  );
}
