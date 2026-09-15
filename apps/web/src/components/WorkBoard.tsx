import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { listActors, type ActorRead } from "../lib/actorsClient";
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
import { WorkCommands, createWorkFromTemplate } from "../lib/workActions";

function statusLabel(status: string): string {
  return statusText(status);
}

function formatBytes(n: number | null): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

type Props = {
  workItems: LocalWorkItem[];
  online: boolean;
  onChanged: () => void;
};

/** Lifecycle actions in order. Reassign omitted until assignee flow is complete. */
function actionsForStatus(status: string): string[] {
  switch (status) {
    case "DRAFT":
      return ["ReleaseWork", "CancelWork"];
    case "READY":
      return ["AssignWork", "CancelWork"];
    case "ASSIGNED":
      return ["AcceptAssignment", "CancelWork"];
    case "ACCEPTED":
      return ["StartWork", "CancelWork"];
    case "IN_PROGRESS":
      return ["SubmitWork", "RaiseException", "CancelWork"];
    case "BLOCKED":
      return ["ResolveException", "SubmitWork", "CancelWork"];
    case "SUBMITTED":
      return ["BeginReview", "WithdrawSubmission"];
    case "UNDER_REVIEW":
      return ["AcceptReview", "RejectSubmission"];
    case "REJECTED":
      return ["ResumeWork", "SubmitWork", "CancelWork"];
    default:
      return [];
  }
}

const EXCEPTION_OUTCOMES = new Set([
  "PARTIALLY_COMPLETED",
  "UNABLE_TO_ACCESS",
  "FAILED",
  "BLOCKED",
  "REFERRED",
  "REQUIRES_FOLLOW_UP",
]);

const ACTION_LABELS: Record<string, string> = {
  ReleaseWork: "Release",
  AssignWork: "Assign",
  AcceptAssignment: "Accept",
  StartWork: "Start",
  SubmitWork: "Submit",
  RaiseException: "Report blocked",
  ResolveException: "Unblock",
  WithdrawSubmission: "Withdraw",
  BeginReview: "Begin review",
  AcceptReview: "Accept review",
  RejectSubmission: "Reject",
  ResumeWork: "Resume",
  CancelWork: "Cancel",
};

const PRIMARY_ACTIONS = new Set([
  "ReleaseWork",
  "AcceptAssignment",
  "StartWork",
  "SubmitWork",
  "ResolveException",
  "BeginReview",
  "AcceptReview",
  "ResumeWork",
]);

const EXCEPTION_CATEGORIES = [
  { id: "no_access", label: "Site unavailable / no access" },
  { id: "unsafe", label: "Unsafe conditions" },
  { id: "wrong_site", label: "Wrong site or wrong assignment" },
  { id: "missing_asset", label: "Equipment or stock missing" },
  { id: "other", label: "Other" },
] as const;

export default function WorkBoard({ workItems, online, onChanged }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [actors, setActors] = useState<ActorRead[]>([]);
  const [templates, setTemplates] = useState<TemplateRead[]>([]);
  const [tasks, setTasks] = useState<LocalWorkTask[]>([]);
  const [pendingEvidence, setPendingEvidence] = useState<PendingEvidence[]>([]);
  const [serverEvidence, setServerEvidence] = useState<EvidenceListItem[]>([]);
  const [openExceptions, setOpenExceptions] = useState<WorkExceptionRow[]>([]);
  const [taskDrafts, setTaskDrafts] = useState<
    Record<string, { notes: string; fieldValues: Record<string, string> }>
  >({});
  const [titleEdit, setTitleEdit] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [reason, setReason] = useState("");
  const [outcomeType, setOutcomeType] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [evidenceType, setEvidenceType] = useState("photo");
  const [evidenceFile, setEvidenceFile] = useState<File | null>(null);
  const [evidenceTaskId, setEvidenceTaskId] = useState("");
  const [titleDraft, setTitleDraft] = useState("");
  const [workTypeDraft, setWorkTypeDraft] = useState("facility_inspection");
  const [exceptionCategory, setExceptionCategory] = useState("");
  const [exceptionDetail, setExceptionDetail] = useState("");

  const selected = workItems.find((w) => w.id === selectedId) ?? null;
  const selectedTemplate = useMemo(
    () => templates.find((t) => t.work_type === selected?.workType) ?? null,
    [templates, selected?.workType],
  );

  const refreshTemplates = useCallback(() => {
    listTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, []);

  const refreshActors = useCallback(() => {
    listActors().then(setActors).catch(() => setActors([]));
  }, []);

  const refreshTasks = useCallback(async (workId: string | null) => {
    if (!workId) {
      setTasks([]);
      return;
    }
    setTasks(await listWorkTasks(workId));
  }, []);

  const refreshEvidence = useCallback(() => {
    listPendingEvidence()
      .then((rows) =>
        setPendingEvidence(selectedId ? rows.filter((r) => r.workItemId === selectedId) : []),
      )
      .catch(() => setPendingEvidence([]));
    if (selectedId) {
      listEvidence(selectedId)
        .then(setServerEvidence)
        .catch(() => setServerEvidence([]));
    } else {
      setServerEvidence([]);
    }
  }, [selectedId]);

  useEffect(() => {
    refreshTemplates();
    refreshActors();
  }, [refreshTemplates, refreshActors]);

  useEffect(() => {
    void refreshTasks(selectedId);
    refreshEvidence();
    setOutcomeType("");
    const item = workItems.find((w) => w.id === selectedId);
    setTitleEdit(item?.title ?? "");
    setTaskDrafts({});
    if (selectedId && (selected?.status === "BLOCKED" || item?.status === "BLOCKED")) {
      listWorkExceptions(selectedId, true)
        .then(setOpenExceptions)
        .catch(() => setOpenExceptions([]));
    } else {
      setOpenExceptions([]);
    }
  }, [selectedId, refreshTasks, refreshEvidence, selected?.status, workItems]);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg(`${label} saved on this device. Use Send pending to upload.`);
      onChanged();
      await refreshTasks(selectedId);
      refreshEvidence();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : `${label} failed`);
    } finally {
      setBusy(false);
    }
  };

  const onCreate = async (e: FormEvent) => {
    e.preventDefault();
    const template = templates.find((t) => t.work_type === workTypeDraft);
    if (!template || !titleDraft.trim()) {
      setMsg("Select a template and enter a title");
      return;
    }
    await run("Create work", async () => {
      const { localWorkId } = await createWorkFromTemplate({
        workType: workTypeDraft,
        title: titleDraft.trim(),
        templateTasks: template.tasks.map((t) => ({
          key: t.key,
          title: t.title,
          description: t.description,
          required: t.required,
          required_evidence_types: t.required_evidence_types,
          fields: t.fields,
        })),
      });
      setTitleDraft("");
      setSelectedId(localWorkId);
    });
  };

  const requiredTasks = tasks.filter((t) => t.required);
  const pendingRequired = requiredTasks.filter((t) => t.status === "PENDING");
  const checklistComplete = tasks.length === 0 || pendingRequired.length === 0;
  const canSubmitException = EXCEPTION_OUTCOMES.has(outcomeType);

  const onAction = async (action: string) => {
    if (!selected) return;
    switch (action) {
      case "ReleaseWork":
        await run("Release", () => WorkCommands.release(selected.id));
        break;
      case "AcceptAssignment":
        await run("Accept", () => WorkCommands.accept(selected.id));
        break;
      case "StartWork":
        await run("Start", () => WorkCommands.start(selected.id));
        break;
      case "SubmitWork": {
        if (tasks.length > 0 && !checklistComplete && !canSubmitException) {
          setMsg(
            `Cannot submit: ${pendingRequired.length} required checklist item(s) still pending.`,
          );
          return;
        }
        const outcome = outcomeType || selectedTemplate?.default_outcome_type || "COMPLETED";
        await run("Submit", () => WorkCommands.submit(selected.id, reason, outcome));
        break;
      }
      case "RaiseException": {
        if (!exceptionCategory) {
          setMsg("Choose what went wrong");
          return;
        }
        if (exceptionCategory === "other" && !exceptionDetail.trim()) {
          setMsg("Describe what went wrong");
          return;
        }
        if (exceptionCategory !== "other" && !exceptionDetail.trim()) {
          setMsg("Add a short note for the supervisor");
          return;
        }
        const composed = `${exceptionCategory}| ${exceptionDetail.trim()}`;
        await run("Report blocked", () => WorkCommands.raiseException(selected.id, composed));
        setExceptionCategory("");
        setExceptionDetail("");
        break;
      }
      case "ResolveException":
        await run("Unblock", () => WorkCommands.resolveException(selected.id));
        break;
      case "WithdrawSubmission":
        await run("Withdraw", () => WorkCommands.withdraw(selected.id));
        break;
      case "BeginReview":
        await run("Begin review", () => WorkCommands.beginReview(selected.id));
        break;
      case "AcceptReview":
        await run("Accept review", () => WorkCommands.acceptReview(selected.id, reason));
        break;
      case "RejectSubmission":
        if (!reason.trim()) {
          setMsg("Reject requires a reason");
          return;
        }
        await run("Reject", () => WorkCommands.rejectReview(selected.id, reason));
        break;
      case "ResumeWork":
        await run("Resume", () => WorkCommands.resume(selected.id));
        break;
      case "AssignWork":
        if (!assigneeId) {
          setMsg("Select an assignee");
          return;
        }
        await run("Assign", () => WorkCommands.assign(selected.id, assigneeId, reason));
        break;
      case "CancelWork":
        if (!reason.trim()) {
          setMsg("Cancel requires a reason");
          return;
        }
        await run("Cancel", () => WorkCommands.cancel(selected.id, reason));
        break;
      default:
        setMsg(`Unknown action ${action}`);
    }
  };

  const onTask = async (task: LocalWorkTask, kind: "complete" | "skip") => {
    if (!selected) return;
    const draft = taskDrafts[task.id] ?? {
      notes: task.notes,
      fieldValues: task.fieldValues,
    };
    await run(kind === "complete" ? `Complete ${task.title}` : `Skip ${task.title}`, () =>
      kind === "complete"
        ? WorkCommands.completeTask(
            selected.id,
            task.id,
            draft.notes,
            draft.fieldValues,
          )
        : WorkCommands.skipTask(selected.id, task.id, draft.notes),
    );
  };

  const onSaveTaskDraft = async (task: LocalWorkTask) => {
    if (!selected) return;
    const draft = taskDrafts[task.id] ?? {
      notes: task.notes,
      fieldValues: task.fieldValues,
    };
    await run("Save answers", () =>
      WorkCommands.saveTaskDraft(selected.id, task.id, draft.notes, draft.fieldValues),
    );
  };

  const onEditTitle = async () => {
    if (!selected || !titleEdit.trim()) return;
    await run("Update title", () => WorkCommands.editWorkTitle(selected.id, titleEdit.trim()));
    onChanged();
  };

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

  const onEvidence = async (e: FormEvent) => {
    e.preventDefault();
    if (!selected || !evidenceFile) {
      setMsg("Choose a file for evidence");
      return;
    }
    await enqueuePendingEvidence({
      workItemId: selected.id,
      workTaskId: evidenceTaskId || undefined,
      evidenceType,
      file: evidenceFile,
      fileName: evidenceFile.name,
    });
    setEvidenceFile(null);
    setEvidenceTaskId("");
    setMsg("Evidence saved on this device. Use Send pending to upload.");
    onChanged();
    refreshEvidence();
  };

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    setEvidenceFile(e.target.files?.[0] ?? null);
  };

  const templateForCreate = templates.find((t) => t.work_type === workTypeDraft);

  return (
    <section className="panel" data-testid="work-board">
      <header className="panel-head">
        <h2>Work</h2>
      </header>

      <form onSubmit={onCreate} className="create-form" data-testid="create-work-form">
        <label>
          Template
          <select value={workTypeDraft} onChange={(e) => setWorkTypeDraft(e.target.value)}>
            {templates.map((t) => (
              <option key={t.id} value={t.work_type}>
                {t.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          Title
          <input
            value={titleDraft}
            onChange={(e) => setTitleDraft(e.target.value)}
            placeholder="e.g. Pump room inspection — Ward B"
            required
          />
        </label>
        <button type="submit" className="btn-primary" disabled={busy || !templateForCreate}>
          Create work
        </button>
      </form>

      <div className="work-layout">
        <aside className="work-list-pane">
          <h3 className="section-label">Queue</h3>
          {workItems.length === 0 ? (
            <p className="muted">No work yet. Create one above.</p>
          ) : (
            <ul className="work-list">
              {workItems.map((w) => (
                <li key={w.id}>
                  <button
                    type="button"
                    className={selectedId === w.id ? "work-link active" : "work-link"}
                    onClick={() => setSelectedId(w.id)}
                  >
                    <span className="work-link-title">{w.title}</span>
                    <span className="work-link-meta">
                      <span className="status-text">{statusLabel(w.status)}</span>
                      {w.localPendingCreate && (
                        <span className="status-text">on device</span>
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <div className="work-detail-pane">
          {!selected ? (
            <p className="muted">Select work from the queue.</p>
          ) : (
            <div className="work-detail">
              <div className="detail-head">
                {["DRAFT", "READY", "ASSIGNED", "ACCEPTED", "IN_PROGRESS", "BLOCKED"].includes(
                  selected.status,
                ) ? (
                  <div className="title-edit">
                    <input
                      value={titleEdit}
                      onChange={(e) => setTitleEdit(e.target.value)}
                      aria-label="Work title"
                    />
                    {titleEdit.trim() && titleEdit.trim() !== selected.title && (
                      <button
                        type="button"
                        className="btn-secondary"
                        disabled={busy}
                        onClick={() => void onEditTitle()}
                      >
                        Save title
                      </button>
                    )}
                  </div>
                ) : (
                  <h3>{selected.title}</h3>
                )}
                <div className="detail-meta">
                  <span className="status-text emphasis">{statusLabel(selected.status)}</span>
                  <span className="muted">
                    {templates.find((t) => t.work_type === selected.workType)?.title ??
                      selected.workType}
                  </span>
                  {selected.localPendingCreate && (
                    <span className="status-text">saved on device</span>
                  )}
                </div>
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
                  <p className="muted">
                    Your supervisor can unblock this work once the issue is cleared.
                  </p>
                </div>
              )}

              {selected.status === "READY" && (
                <label className="block">
                  Assign to
                  <select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}>
                    <option value="">Select…</option>
                    {actors.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.display_name}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {["IN_PROGRESS", "BLOCKED", "ACCEPTED", "SUBMITTED"].includes(selected.status) && (
                <label className="block">
                  Note / reason
                  <input
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Required for reject or cancel"
                  />
                </label>
              )}

              {["IN_PROGRESS", "ACCEPTED"].includes(selected.status) && (
                <div className="exception-box" data-testid="exception-box">
                  <h4>If you cannot continue</h4>
                  <label className="block">
                    What happened
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
                      Details
                      <input
                        value={exceptionDetail}
                        onChange={(e) => setExceptionDetail(e.target.value)}
                        placeholder="Short factual note for your supervisor"
                      />
                    </label>
                  )}
                  <p className="muted">
                    This blocks the work and notifies review. Do not mark complete if the job
                    was not done.
                  </p>
                </div>
              )}

              {tasks.length > 0 && (
                <div className="checklist" data-testid="checklist">
                  <div className="checklist-head">
                    <h4>Checklist</h4>
                    <span className="muted">
                      {requiredTasks.length - pendingRequired.length}/{requiredTasks.length}{" "}
                      required done
                    </span>
                  </div>
                  <ul className="task-list">
                    {tasks.map((t) => {
                      const draft = taskDrafts[t.id] ?? {
                        notes: t.notes,
                        fieldValues: t.fieldValues,
                      };
                      const editable =
                        ["IN_PROGRESS", "BLOCKED", "ACCEPTED"].includes(selected.status) &&
                        t.status === "PENDING";
                      return (
                        <li key={t.id} className={`task-row status-${t.status}`}>
                          <div className="task-meta">
                            <strong>
                              {t.sequence}. {t.title}
                            </strong>
                            <span className="status-text">
                              {t.required ? "Required" : "Optional"}
                            </span>
                            <span className="status-text">
                              {t.status === "PENDING"
                                ? "To do"
                                : t.status === "COMPLETED"
                                  ? "Done"
                                  : "Skipped"}
                            </span>
                            {t.requiredEvidenceTypes.length > 0 && (
                              <span className="muted">
                                needs {t.requiredEvidenceTypes.join(", ")}
                              </span>
                            )}
                          </div>
                          {t.description && <p className="muted">{t.description}</p>}
                          {editable && (
                            <div className="task-form">
                              {t.fields.map((f) => (
                                <label key={f.key} className="block">
                                  {f.label}
                                  {f.type === "choice" && f.options?.length ? (
                                    <select
                                      value={draft.fieldValues[f.key] ?? ""}
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
                                      value={draft.fieldValues[f.key] ?? ""}
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
                                  value={draft.notes}
                                  onChange={(e) => setDraftNotes(t.id, e.target.value)}
                                  placeholder="Optional notes"
                                />
                              </label>
                              <div className="actions">
                                <button
                                  type="button"
                                  className="btn-secondary"
                                  disabled={busy}
                                  onClick={() => void onSaveTaskDraft(t)}
                                >
                                  Save answers
                                </button>
                                <button
                                  type="button"
                                  className="btn-primary"
                                  disabled={busy}
                                  onClick={() => void onTask(t, "complete")}
                                >
                                  Mark done
                                </button>
                                {!t.required && (
                                  <button
                                    type="button"
                                    className="btn-secondary"
                                    disabled={busy}
                                    onClick={() => void onTask(t, "skip")}
                                  >
                                    Skip
                                  </button>
                                )}
                              </div>
                            </div>
                          )}
                          {t.status !== "PENDING" && (
                            <p className="muted">
                              {Object.entries(t.fieldValues)
                                .map(([k, v]) => `${k}: ${v}`)
                                .join(" · ")}
                              {t.notes ? ` — ${t.notes}` : ""}
                            </p>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}

              {["IN_PROGRESS", "BLOCKED", "ACCEPTED"].includes(selected.status) && (
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
                    <p className="warn" data-testid="submit-blocked">
                      Complete required checklist items before submit (or choose an exception
                      outcome).
                    </p>
                  )}
                </>
              )}

              <div className="actions">
                {actionsForStatus(selected.status).map((action) => (
                  <button
                    key={action}
                    type="button"
                    className={PRIMARY_ACTIONS.has(action) ? "btn-primary" : "btn-secondary"}
                    disabled={busy}
                    onClick={() => void onAction(action)}
                  >
                    {ACTION_LABELS[action] ?? action}
                  </button>
                ))}
              </div>

              {["IN_PROGRESS", "BLOCKED", "ACCEPTED"].includes(selected.status) && (
                <form onSubmit={(e) => void onEvidence(e)} className="evidence-form">
                  <h4>Evidence</h4>
                  <label>
                    Bind to task
                    <select
                      value={evidenceTaskId}
                      onChange={(e) => setEvidenceTaskId(e.target.value)}
                    >
                      <option value="">Work item</option>
                      {tasks.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.sequence}. {t.title}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Type
                    <select value={evidenceType} onChange={(e) => setEvidenceType(e.target.value)}>
                      <option value="photo">photo</option>
                      <option value="document">document</option>
                      <option value="observation">observation</option>
                    </select>
                  </label>
                  <input type="file" accept="image/*,application/pdf" onChange={onFile} />
                  <button
                    type="submit"
                    className="btn-primary"
                    disabled={busy || !evidenceFile}
                  >
                    Add evidence
                  </button>
                  {pendingEvidence.length > 0 && (
                    <ul className="task-list">
                      {pendingEvidence.map((p) => (
                        <li key={p.localId} className="task-row">
                          {p.evidenceType} · {p.fileName ?? "file"} · waiting to send
                        </li>
                      ))}
                    </ul>
                  )}
                  {serverEvidence.length > 0 && (
                    <ul className="task-list" data-testid="server-evidence">
                      {serverEvidence.map((ev) => (
                        <li key={ev.id} className="task-row evidence-row">
                          <span>
                            {ev.evidence_type} · {formatBytes(ev.size_bytes)} ·{" "}
                            {statusLabel(ev.verification_status) === ev.verification_status
                              ? "stored"
                              : "stored"}
                          </span>
                          {ev.verification_status === "UPLOADED" ||
                          ev.verification_status === "VERIFIED" ? (
                            <button
                              type="button"
                              className="btn-secondary"
                              onClick={() => void download(ev)}
                            >
                              Download
                            </button>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </form>
              )}

              {!online && (
                <p className="warn">Offline — changes stay on this device until you Send pending.</p>
              )}
            </div>
          )}
        </div>
      </div>

      {msg && <p data-testid="work-board-msg">{msg}</p>}
    </section>
  );
}
